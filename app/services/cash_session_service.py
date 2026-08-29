"""Service d'ouverture / fermeture de caisse (preuve d'écart)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.cash_session import STATUS_CLOSED, STATUS_OPEN, CashSession
from app.models.debt import DebtPayment
from app.models.expense import Expense
from app.models.sale import Payment, Sale
from app.services import audit_service
from app.utils.helpers import to_float


class CashSessionService:
    @staticmethod
    def get_open(user_id: int) -> Optional[CashSession]:
        with session_scope() as session:
            row = session.scalar(
                select(CashSession)
                .options(joinedload(CashSession.user))
                .where(
                    CashSession.user_id == user_id,
                    CashSession.status == STATUS_OPEN,
                )
                .order_by(CashSession.opened_at.desc())
            )
            if row:
                session.expunge(row)
            return row

    @staticmethod
    def open_session(user_id: int, opening_float: float = 0, *, username: str = "") -> CashSession:
        opening_float = round(to_float(opening_float), 2)
        if opening_float < 0:
            raise ValueError("Le fond de caisse ne peut pas être négatif.")
        existing = CashSessionService.get_open(user_id)
        if existing:
            raise ValueError("Une session de caisse est déjà ouverte.")
        with session_scope() as session:
            row = CashSession(
                user_id=user_id,
                opened_at=datetime.now(),
                opening_float=opening_float,
                status=STATUS_OPEN,
            )
            session.add(row)
            session.flush()
            session_id = row.id
        audit_service.log_action(
            "Ouverture caisse",
            "CashSession",
            f"id={session_id} fond={opening_float}",
            user_id,
            username,
        )
        return CashSessionService.get(session_id)  # type: ignore[return-value]

    @staticmethod
    def get(session_id: int) -> Optional[CashSession]:
        with session_scope() as session:
            row = session.get(CashSession, session_id)
            if row:
                session.expunge(row)
            return row

    @staticmethod
    def compute_expected(session_id: int) -> float:
        """Fond + encaissements espèces (ventes + règlements dettes) − dépenses."""
        with session_scope() as session:
            cash = session.get(CashSession, session_id)
            if not cash:
                raise ValueError("Session introuvable.")
            lo = cash.opened_at
            hi = cash.closed_at or datetime.now()
            user_id = cash.user_id
            opening = float(cash.opening_float or 0)

            sales_cash = float(
                session.scalar(
                    select(func.coalesce(func.sum(Payment.amount), 0))
                    .join(Sale, Sale.id == Payment.sale_id)
                    .where(
                        Sale.user_id == user_id,
                        Sale.status == "completed",
                        Sale.date >= lo,
                        Sale.date <= hi,
                        Payment.method == "Espèces",
                    )
                )
                or 0
            )
            debt_cash = float(
                session.scalar(
                    select(func.coalesce(func.sum(DebtPayment.amount), 0)).where(
                        DebtPayment.created_by == user_id,
                        DebtPayment.payment_date >= lo,
                        DebtPayment.payment_date <= hi,
                        DebtPayment.payment_method == "Espèces",
                    )
                )
                or 0
            )
            expenses = float(
                session.scalar(
                    select(func.coalesce(func.sum(Expense.amount), 0)).where(
                        Expense.date >= lo,
                        Expense.date <= hi,
                    )
                )
                or 0
            )
            # Les dépenses ne sont pas toujours liées à un user : on les ignore
            # pour l'écart perso caissier (sinon fausse accusation).
            _ = expenses
            return round(opening + sales_cash + debt_cash, 2)

    @staticmethod
    def close_session(
        session_id: int,
        counted: float,
        *,
        note: str = "",
        user_id: Optional[int] = None,
        username: str = "",
    ) -> CashSession:
        counted = round(to_float(counted), 2)
        if counted < 0:
            raise ValueError("Le montant compté ne peut pas être négatif.")
        expected = CashSessionService.compute_expected(session_id)
        variance = round(counted - expected, 2)
        with session_scope() as session:
            cash = session.get(CashSession, session_id)
            if not cash or cash.status != STATUS_OPEN:
                raise ValueError("Aucune session ouverte à fermer.")
            cash.closed_at = datetime.now()
            cash.closing_counted = counted
            cash.expected_cash = expected
            cash.variance = variance
            cash.status = STATUS_CLOSED
            cash.note = (note or "").strip()
        audit_service.log_action(
            "Fermeture caisse",
            "CashSession",
            f"id={session_id} compté={counted} attendu={expected} écart={variance}",
            user_id,
            username,
        )
        return CashSessionService.get(session_id)  # type: ignore[return-value]

    @staticmethod
    def recent(limit: int = 30) -> List[CashSession]:
        with session_scope() as session:
            rows = session.scalars(
                select(CashSession)
                .options(joinedload(CashSession.user))
                .order_by(CashSession.opened_at.desc())
                .limit(limit)
            ).unique().all()
            session.expunge_all()
            return list(rows)
