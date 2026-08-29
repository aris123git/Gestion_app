"""Service des dettes clients.

Source de vérité : tables ``debts`` / ``debt_payments``.
Le champ ``Client.debt`` est un cache synchronisé après chaque opération.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.database.connection import session_scope
from app.models.client import Client
from app.models.debt import (
    ACTIVE_DEBT_STATUSES,
    STATUS_CANCELLED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_PARTIAL,
    Debt,
    DebtPayment,
)
from app.services import audit_service
from app.utils.helpers import to_float


class DebtService:
    """Logique métier des créances et remboursements clients."""

    # --- Synchronisation du cache ------------------------------------------
    @staticmethod
    def sync_client_debt_cache(session: Session, client_id: int) -> float:
        """Recalcule ``Client.debt`` à partir des dettes actives. Retourne le solde."""
        total = session.scalar(
            select(func.coalesce(func.sum(Debt.amount_remaining), 0)).where(
                Debt.client_id == client_id,
                Debt.status.in_(ACTIVE_DEBT_STATUSES),
            )
        )
        balance = round(float(total or 0), 2)
        client = session.get(Client, client_id)
        if client:
            client.debt = balance
        return balance

    @staticmethod
    def _refresh_status(debt: Debt) -> None:
        if debt.status == STATUS_CANCELLED:
            return
        remaining = float(debt.amount_remaining)
        initial = float(debt.amount_initial)
        if remaining <= 0:
            debt.amount_remaining = 0
            debt.status = STATUS_PAID
        elif remaining < initial:
            debt.status = STATUS_PARTIAL
        else:
            debt.status = STATUS_OPEN

    # --- Création ----------------------------------------------------------
    @classmethod
    def create_debt(
        cls,
        client_id: int,
        amount: float,
        *,
        sale_id: Optional[int] = None,
        due_date: Optional[date] = None,
        note: str = "",
        user_id: Optional[int] = None,
        username: str = "",
        session: Optional[Session] = None,
    ) -> Optional[Debt]:
        """Crée une dette et synchronise le cache client."""
        amount = round(to_float(amount), 2)
        if amount <= 0:
            return None

        def _do(sess: Session) -> Debt:
            client = sess.get(Client, client_id)
            if not client:
                raise ValueError("Client introuvable.")
            debt = Debt(
                client_id=client_id,
                sale_id=sale_id,
                amount_initial=amount,
                amount_remaining=amount,
                due_date=due_date,
                status=STATUS_OPEN,
                note=(note or "").strip(),
            )
            sess.add(debt)
            sess.flush()
            cls.sync_client_debt_cache(sess, client_id)
            return debt

        details = f"client={client_id} montant={amount} sale={sale_id or '-'}"
        if session is not None:
            # Pas d'audit ici : évite un verrou SQLite (session imbriquée).
            # L'appelant journalise après commit si besoin.
            return _do(session)

        with session_scope() as sess:
            debt = _do(sess)
            sess.flush()
            debt_id = debt.id
        audit_service.log_action(
            "Création dette", "Debt", details, user_id, username
        )
        return cls.get(debt_id)

    # --- Paiements ---------------------------------------------------------
    @classmethod
    def pay_debt(
        cls,
        debt_id: int,
        amount: float,
        *,
        payment_method: str = "Espèces",
        payment_date: Optional[datetime] = None,
        note: str = "",
        user_id: Optional[int] = None,
        username: str = "",
    ) -> DebtPayment:
        """Rembourse une dette précise (partiel ou total)."""
        amount = round(to_float(amount), 2)
        if amount <= 0:
            raise ValueError("Le montant doit être supérieur à zéro.")

        with session_scope() as session:
            debt = session.get(Debt, debt_id)
            if not debt or debt.status == STATUS_CANCELLED:
                raise ValueError("Dette introuvable ou annulée.")
            remaining = float(debt.amount_remaining)
            if remaining <= 0:
                raise ValueError("Cette dette est déjà soldée.")
            if amount > remaining:
                raise ValueError(
                    f"Montant trop élevé : reste dû {remaining:,.0f}."
                )
            payment = DebtPayment(
                debt_id=debt.id,
                amount=amount,
                payment_method=payment_method or "Espèces",
                payment_date=payment_date or datetime.now(),
                created_by=user_id,
                note=(note or "").strip(),
            )
            session.add(payment)
            debt.amount_remaining = round(remaining - amount, 2)
            cls._refresh_status(debt)
            cls.sync_client_debt_cache(session, debt.client_id)
            session.flush()
            payment_id = payment.id
            client_id = debt.client_id

        audit_service.log_action(
            "Remboursement dette",
            "DebtPayment",
            f"debt={debt_id} client={client_id} montant={amount} "
            f"méthode={payment_method}",
            user_id,
            username,
        )
        return cls.get_payment(payment_id)  # type: ignore[return-value]

    @classmethod
    def pay_client(
        cls,
        client_id: int,
        amount: float,
        *,
        payment_method: str = "Espèces",
        payment_date: Optional[datetime] = None,
        note: str = "",
        user_id: Optional[int] = None,
        username: str = "",
    ) -> List[DebtPayment]:
        """Répartit un paiement sur les dettes actives (FIFO par date)."""
        amount = round(to_float(amount), 2)
        if amount <= 0:
            raise ValueError("Le montant doit être supérieur à zéro.")

        created: List[int] = []
        with session_scope() as session:
            debts = list(
                session.scalars(
                    select(Debt)
                    .where(
                        Debt.client_id == client_id,
                        Debt.status.in_(ACTIVE_DEBT_STATUSES),
                        Debt.amount_remaining > 0,
                    )
                    .order_by(Debt.created_at.asc(), Debt.id.asc())
                ).all()
            )
            if not debts:
                raise ValueError("Aucune dette active pour ce client.")
            total_due = sum(float(d.amount_remaining) for d in debts)
            if amount > total_due + 0.001:
                raise ValueError(
                    f"Montant trop élevé : solde dû {total_due:,.0f}."
                )
            left = amount
            for debt in debts:
                if left <= 0:
                    break
                take = min(left, float(debt.amount_remaining))
                payment = DebtPayment(
                    debt_id=debt.id,
                    amount=take,
                    payment_method=payment_method or "Espèces",
                    payment_date=payment_date or datetime.now(),
                    created_by=user_id,
                    note=(note or "").strip(),
                )
                session.add(payment)
                debt.amount_remaining = round(float(debt.amount_remaining) - take, 2)
                cls._refresh_status(debt)
                session.flush()
                created.append(payment.id)
                left = round(left - take, 2)
            cls.sync_client_debt_cache(session, client_id)

        audit_service.log_action(
            "Remboursement dette",
            "DebtPayment",
            f"client={client_id} montant={amount} méthode={payment_method} "
            f"paiements={len(created)}",
            user_id,
            username,
        )
        return [p for pid in created if (p := cls.get_payment(pid))]

    # --- Annulation --------------------------------------------------------
    @classmethod
    def cancel_debt(
        cls,
        debt_id: int,
        *,
        user_id: Optional[int] = None,
        username: str = "",
        reason: str = "",
        session: Optional[Session] = None,
    ) -> None:
        """Annule une dette (ex. vente annulée) et resynchronise le cache."""

        def _do(sess: Session) -> Optional[int]:
            debt = sess.get(Debt, debt_id)
            if not debt or debt.status == STATUS_CANCELLED:
                return None
            client_id = debt.client_id
            debt.status = STATUS_CANCELLED
            debt.amount_remaining = 0
            if reason:
                suffix = f" | Annulation : {reason}"
                debt.note = ((debt.note or "") + suffix).strip(" |")
            cls.sync_client_debt_cache(sess, client_id)
            return client_id

        if session is not None:
            return _do(session)

        with session_scope() as sess:
            client_id = _do(sess)
        if client_id is not None:
            audit_service.log_action(
                "Annulation dette",
                "Debt",
                f"debt={debt_id} client={client_id} {reason}".strip(),
                user_id,
                username,
            )

    @classmethod
    def cancel_debts_for_sale(
        cls,
        sale_id: int,
        *,
        user_id: Optional[int] = None,
        username: str = "",
        session: Optional[Session] = None,
    ) -> int:
        """Annule toutes les dettes liées à une vente. Retourne le nombre."""

        def _do(sess: Session) -> int:
            debts = list(
                sess.scalars(select(Debt).where(Debt.sale_id == sale_id)).all()
            )
            count = 0
            for debt in debts:
                if debt.status == STATUS_CANCELLED:
                    continue
                debt.status = STATUS_CANCELLED
                debt.amount_remaining = 0
                debt.note = ((debt.note or "") + " | Annulation vente").strip(" |")
                cls.sync_client_debt_cache(sess, debt.client_id)
                count += 1
            return count

        if session is not None:
            return _do(session)

        with session_scope() as sess:
            count = _do(sess)
        if count:
            audit_service.log_action(
                "Annulation dette",
                "Debt",
                f"sale={sale_id} dettes_annulées={count}",
                user_id,
                username,
            )
        return count

    # --- Lecture -----------------------------------------------------------
    @staticmethod
    def get(debt_id: int) -> Optional[Debt]:
        with session_scope() as session:
            debt = session.scalar(
                select(Debt)
                .options(
                    joinedload(Debt.client),
                    joinedload(Debt.sale),
                    joinedload(Debt.payments),
                )
                .where(Debt.id == debt_id)
            )
            if debt:
                session.expunge_all()
            return debt

    @staticmethod
    def get_payment(payment_id: int) -> Optional[DebtPayment]:
        with session_scope() as session:
            payment = session.get(DebtPayment, payment_id)
            if payment:
                session.expunge(payment)
            return payment

    @staticmethod
    def list_debts(
        client_id: Optional[int] = None,
        status: Optional[str] = None,
        search: str = "",
        only_active: bool = False,
        filter_mode: Optional[str] = None,
        sort_by: str = "recent",
        limit: int = 500,
    ) -> List[Debt]:
        """Liste les dettes, plus récentes d'abord par défaut.

        ``filter_mode`` :
          - ``unpaid`` : non soldées (en cours / partielles)
          - ``paid`` : soldées
          - ``overdue`` : échéance dépassée et reste dû > 0
          - ``all`` / ``None`` : toutes (hors filtre status/only_active)

        ``sort_by`` : ``recent`` | ``due_date`` | ``remaining`` | ``client``
        """
        with session_scope() as session:
            query = select(Debt).options(
                joinedload(Debt.client),
                joinedload(Debt.sale),
            )
            if client_id:
                query = query.where(Debt.client_id == client_id)
            if status:
                query = query.where(Debt.status == status)
            if only_active:
                query = query.where(Debt.status.in_(ACTIVE_DEBT_STATUSES))

            mode = (filter_mode or "").strip().lower()
            today = date.today()
            if mode == "unpaid":
                query = query.where(
                    Debt.status.in_(ACTIVE_DEBT_STATUSES),
                    Debt.amount_remaining > 0,
                )
            elif mode == "paid":
                query = query.where(Debt.status == STATUS_PAID)
            elif mode == "overdue":
                query = query.where(
                    Debt.status.in_(ACTIVE_DEBT_STATUSES),
                    Debt.amount_remaining > 0,
                    Debt.due_date.is_not(None),
                    Debt.due_date < today,
                )
            elif mode in ("all", ""):
                pass
            elif mode == "cancelled":
                query = query.where(Debt.status == STATUS_CANCELLED)

            needs_client_join = bool(search) or sort_by == "client"
            if needs_client_join:
                query = query.join(Client)

            if search:
                pattern = f"%{search}%"
                query = query.where(
                    or_(
                        Client.name.ilike(pattern),
                        Client.phone.ilike(pattern),
                        Debt.note.ilike(pattern),
                        Debt.status.ilike(pattern),
                    )
                )

            if sort_by == "due_date":
                # Échéances les plus proches / dépassées d'abord ; sans échéance en bas.
                query = query.order_by(
                    case((Debt.due_date.is_(None), 1), else_=0),
                    Debt.due_date.asc(),
                    Debt.created_at.desc(),
                )
            elif sort_by == "remaining":
                query = query.order_by(
                    Debt.amount_remaining.desc(),
                    Debt.created_at.desc(),
                )
            elif sort_by == "client":
                query = query.order_by(
                    Client.name.asc(),
                    Debt.created_at.desc(),
                )
            else:
                # Plus récentes d'abord (défaut).
                query = query.order_by(Debt.created_at.desc(), Debt.id.desc())

            query = query.limit(limit)
            rows = session.scalars(query).unique().all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def sum_manual_repayments(start, end) -> float:
        """Total des règlements de dettes hors vente (entrée libre admin).

        Ces encaissements n'ont pas de ``Sale.profit`` associé : ils doivent
        entrer dans le bénéfice (contrairement aux dettes issues d'une vente
        à crédit, déjà comptées au moment de la vente).
        """
        from datetime import date, datetime, time

        lo = datetime.combine(start, time.min)
        hi = datetime.combine(end, time.max)
        with session_scope() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(DebtPayment.amount), 0))
                .join(Debt, Debt.id == DebtPayment.debt_id)
                .where(
                    DebtPayment.payment_date >= lo,
                    DebtPayment.payment_date <= hi,
                    Debt.sale_id.is_(None),
                )
            )
            return float(total or 0)

    @staticmethod
    def list_payments(
        debt_id: Optional[int] = None,
        client_id: Optional[int] = None,
        limit: int = 500,
    ) -> List[DebtPayment]:
        with session_scope() as session:
            query = select(DebtPayment).options(
                joinedload(DebtPayment.debt).joinedload(Debt.client),
                joinedload(DebtPayment.user),
            )
            if debt_id:
                query = query.where(DebtPayment.debt_id == debt_id)
            if client_id:
                query = query.join(Debt).where(Debt.client_id == client_id)
            query = query.order_by(DebtPayment.payment_date.desc()).limit(limit)
            rows = session.scalars(query).unique().all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def client_summary(client_id: int) -> dict:
        """Résumé des dettes d'un client (solde, actives, échéances)."""
        debts = DebtService.list_debts(client_id=client_id, limit=1000)
        active = [d for d in debts if d.is_active]
        overdue = [d for d in active if d.is_overdue]
        return {
            "total_remaining": round(sum(float(d.amount_remaining) for d in active), 2),
            "active_count": len(active),
            "overdue_count": len(overdue),
            "debts": debts,
        }

    @staticmethod
    def summaries_for_clients(client_ids: list[int]) -> dict[int, dict]:
        """Résumés de dettes pour plusieurs clients en une seule agrégation SQL."""
        ids = [int(client_id) for client_id in client_ids if client_id]
        if not ids:
            return {}
        def empty_summary() -> dict:
            return {
                "total_remaining": 0.0,
                "active_count": 0,
                "overdue_count": 0,
                "debts": [],
            }

        summaries = {client_id: empty_summary() for client_id in ids}
        today = date.today()
        with session_scope() as session:
            rows = session.execute(
                select(
                    Debt.client_id,
                    func.coalesce(func.sum(Debt.amount_remaining), 0),
                    func.count(Debt.id),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (Debt.due_date.is_not(None))
                                    & (Debt.due_date < today)
                                    & (Debt.amount_remaining > 0),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .where(
                    Debt.client_id.in_(ids),
                    Debt.status.in_(ACTIVE_DEBT_STATUSES),
                    Debt.amount_remaining > 0,
                )
                .group_by(Debt.client_id)
            ).all()
        for client_id, total_remaining, active_count, overdue_count in rows:
            summaries[int(client_id)] = {
                "total_remaining": round(float(total_remaining or 0), 2),
                "active_count": int(active_count or 0),
                "overdue_count": int(overdue_count or 0),
                "debts": [],
            }
        return summaries
