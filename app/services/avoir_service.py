"""Service avoirs clients."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from sqlalchemy import select

from app.database.connection import session_scope
from app.models.avoir import (
    ACTIVE_AVOIR_STATUSES,
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_PARTIAL,
    STATUS_USED,
    TYPE_CASH,
    Avoir,
    AvoirRedemption,
)


class AvoirService:
    @staticmethod
    def list(active_only: bool = False, limit: int = 200) -> List[Avoir]:
        with session_scope() as session:
            q = select(Avoir).order_by(Avoir.id.desc()).limit(limit)
            if active_only:
                q = q.where(Avoir.status.in_(ACTIVE_AVOIR_STATUSES))
            return list(session.scalars(q).unique().all())

    @staticmethod
    def get(avoir_id: int) -> Optional[Avoir]:
        with session_scope() as session:
            return session.get(Avoir, avoir_id)

    @staticmethod
    def create(
        *,
        amount: float,
        customer_name: str = "",
        client_id: Optional[int] = None,
        reason: str = "",
        note: str = "",
        expires_on: Optional[date] = None,
        created_by: Optional[int] = None,
        avoir_type: str = TYPE_CASH,
    ) -> Avoir:
        if float(amount) <= 0:
            raise ValueError("Le montant de l'avoir doit être positif.")
        with session_scope() as session:
            avoir = Avoir(
                client_id=client_id,
                customer_name=(customer_name or "").strip(),
                avoir_type=avoir_type or TYPE_CASH,
                amount_initial=float(amount),
                amount_remaining=float(amount),
                reason=(reason or "").strip(),
                note=(note or "").strip(),
                expires_on=expires_on,
                status=STATUS_ACTIVE,
                created_by=created_by,
            )
            session.add(avoir)
            session.flush()
            session.refresh(avoir)
            session.expunge(avoir)
            return avoir

    @staticmethod
    def redeem(
        avoir_id: int,
        amount: float,
        *,
        sale_id: Optional[int] = None,
        note: str = "",
    ) -> Avoir:
        if float(amount) <= 0:
            raise ValueError("Montant d'utilisation invalide.")
        with session_scope() as session:
            avoir = session.get(Avoir, avoir_id)
            if not avoir:
                raise ValueError("Avoir introuvable.")
            if avoir.status not in ACTIVE_AVOIR_STATUSES:
                raise ValueError("Cet avoir n'est plus utilisable.")
            remaining = float(avoir.amount_remaining)
            if float(amount) > remaining + 0.001:
                raise ValueError(
                    f"Montant trop élevé (reste {remaining:.0f})."
                )
            new_rem = round(remaining - float(amount), 2)
            avoir.amount_remaining = new_rem
            if new_rem <= 0.001:
                avoir.status = STATUS_USED
                avoir.amount_remaining = 0
            else:
                avoir.status = STATUS_PARTIAL
            session.add(
                AvoirRedemption(
                    avoir_id=avoir.id,
                    sale_id=sale_id,
                    amount=float(amount),
                    note=(note or "").strip(),
                )
            )
            session.flush()
            session.refresh(avoir)
            session.expunge(avoir)
            return avoir

    @staticmethod
    def cancel(avoir_id: int) -> Avoir:
        with session_scope() as session:
            avoir = session.get(Avoir, avoir_id)
            if not avoir:
                raise ValueError("Avoir introuvable.")
            avoir.status = STATUS_CANCELLED
            session.flush()
            session.refresh(avoir)
            session.expunge(avoir)
            return avoir
