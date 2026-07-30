"""Service des dettes fournisseurs (miroir de DebtService clients)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database.connection import session_scope
from app.models.debt import (
    ACTIVE_DEBT_STATUSES,
    STATUS_CANCELLED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_PARTIAL,
)
from app.models.supplier import Supplier
from app.models.supplier_debt import SupplierDebt, SupplierDebtPayment
from app.services import audit_service
from app.utils.helpers import to_float


class SupplierDebtService:
    """Créances fournisseurs : ledger + cache optionnel sur le fournisseur."""

    @staticmethod
    def _refresh_status(debt: SupplierDebt) -> None:
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

    @classmethod
    def create_debt(
        cls,
        supplier_id: int,
        amount: float,
        *,
        purchase_id: Optional[int] = None,
        note: str = "",
        user_id: Optional[int] = None,
        username: str = "",
        session: Optional[Session] = None,
    ) -> Optional[SupplierDebt]:
        amount = round(to_float(amount), 2)
        if amount <= 0:
            return None

        def _do(sess: Session) -> SupplierDebt:
            if not sess.get(Supplier, supplier_id):
                raise ValueError("Fournisseur introuvable.")
            debt = SupplierDebt(
                supplier_id=supplier_id,
                purchase_id=purchase_id,
                amount_initial=amount,
                amount_remaining=amount,
                status=STATUS_OPEN,
                note=(note or "").strip(),
            )
            sess.add(debt)
            sess.flush()
            return debt

        if session is not None:
            return _do(session)

        with session_scope() as sess:
            debt = _do(sess)
            debt_id = debt.id
        audit_service.log_action(
            "Création dette fournisseur",
            "SupplierDebt",
            f"supplier={supplier_id} montant={amount} purchase={purchase_id or '-'}",
            user_id,
            username,
        )
        return cls.get(debt_id)

    @classmethod
    def pay_supplier(
        cls,
        supplier_id: int,
        amount: float,
        *,
        payment_method: str = "Espèces",
        note: str = "",
        user_id: Optional[int] = None,
        username: str = "",
    ) -> List[SupplierDebtPayment]:
        amount = round(to_float(amount), 2)
        if amount <= 0:
            raise ValueError("Le montant doit être supérieur à zéro.")
        created: List[int] = []
        with session_scope() as session:
            debts = list(
                session.scalars(
                    select(SupplierDebt)
                    .where(
                        SupplierDebt.supplier_id == supplier_id,
                        SupplierDebt.status.in_(ACTIVE_DEBT_STATUSES),
                        SupplierDebt.amount_remaining > 0,
                    )
                    .order_by(SupplierDebt.created_at.asc(), SupplierDebt.id.asc())
                ).all()
            )
            if not debts:
                raise ValueError("Aucune dette active pour ce fournisseur.")
            total_due = sum(float(d.amount_remaining) for d in debts)
            if amount > total_due + 0.001:
                raise ValueError(f"Montant trop élevé : solde dû {total_due:,.0f}.")
            left = amount
            for debt in debts:
                if left <= 0:
                    break
                take = min(left, float(debt.amount_remaining))
                payment = SupplierDebtPayment(
                    debt_id=debt.id,
                    amount=take,
                    payment_method=payment_method or "Espèces",
                    payment_date=datetime.now(),
                    created_by=user_id,
                    note=(note or "").strip(),
                )
                session.add(payment)
                debt.amount_remaining = round(float(debt.amount_remaining) - take, 2)
                cls._refresh_status(debt)
                session.flush()
                created.append(payment.id)
                left = round(left - take, 2)
        audit_service.log_action(
            "Remboursement dette fournisseur",
            "SupplierDebtPayment",
            f"supplier={supplier_id} montant={amount}",
            user_id,
            username,
        )
        return [p for pid in created if (p := cls.get_payment(pid))]

    @staticmethod
    def total_remaining(supplier_id: Optional[int] = None) -> float:
        with session_scope() as session:
            query = select(
                func.coalesce(func.sum(SupplierDebt.amount_remaining), 0)
            ).where(SupplierDebt.status.in_(ACTIVE_DEBT_STATUSES))
            if supplier_id:
                query = query.where(SupplierDebt.supplier_id == supplier_id)
            return float(session.scalar(query) or 0)

    @staticmethod
    def get(debt_id: int) -> Optional[SupplierDebt]:
        with session_scope() as session:
            debt = session.scalar(
                select(SupplierDebt)
                .options(joinedload(SupplierDebt.supplier))
                .where(SupplierDebt.id == debt_id)
            )
            if debt:
                session.expunge_all()
            return debt

    @staticmethod
    def get_payment(payment_id: int) -> Optional[SupplierDebtPayment]:
        with session_scope() as session:
            payment = session.get(SupplierDebtPayment, payment_id)
            if payment:
                session.expunge(payment)
            return payment

    @staticmethod
    def list_debts(
        supplier_id: Optional[int] = None,
        only_active: bool = False,
        limit: int = 500,
    ) -> List[SupplierDebt]:
        with session_scope() as session:
            query = select(SupplierDebt).options(joinedload(SupplierDebt.supplier))
            if supplier_id:
                query = query.where(SupplierDebt.supplier_id == supplier_id)
            if only_active:
                query = query.where(SupplierDebt.status.in_(ACTIVE_DEBT_STATUSES))
            query = query.order_by(SupplierDebt.created_at.desc()).limit(limit)
            rows = session.scalars(query).unique().all()
            session.expunge_all()
            return list(rows)
