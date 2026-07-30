"""Service de fidélité clients (points)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.database.connection import session_scope
from app.models.loyalty import CustomerPoints, CustomerPointsHistory
from app.services import audit_service
from app.utils.helpers import to_float


class LoyaltyService:
    @staticmethod
    def _ensure_account(session: Session, client_id: int) -> CustomerPoints:
        account = session.scalar(
            select(CustomerPoints).where(CustomerPoints.client_id == client_id)
        )
        if account:
            return account
        account = CustomerPoints(client_id=client_id, points=0, lifetime_points=0)
        session.add(account)
        session.flush()
        return account

    @classmethod
    def get_balance(cls, client_id: int) -> float:
        with session_scope() as session:
            account = session.scalar(
                select(CustomerPoints).where(CustomerPoints.client_id == client_id)
            )
            return float(account.points) if account else 0.0

    @classmethod
    def add_points_for_sale(
        cls,
        client_id: int,
        sale_total: float,
        sale_id: Optional[int] = None,
        *,
        user_id: Optional[int] = None,
        session: Optional[Session] = None,
    ) -> float:
        """Ajoute des points proportionnels au montant de la vente."""
        points = round(to_float(sale_total) * config.LOYALTY_POINTS_PER_CURRENCY, 2)
        if points <= 0 or not client_id:
            return 0.0

        def _do(sess: Session) -> float:
            account = cls._ensure_account(sess, client_id)
            account.points = float(account.points) + points
            account.lifetime_points = float(account.lifetime_points) + points
            sess.add(
                CustomerPointsHistory(
                    client_id=client_id,
                    delta=points,
                    balance_after=float(account.points),
                    reason="Vente",
                    sale_id=sale_id,
                    user_id=user_id,
                )
            )
            return points

        if session is not None:
            return _do(session)
        with session_scope() as sess:
            return _do(sess)

    @classmethod
    def redeem(
        cls,
        client_id: int,
        points: float,
        *,
        note: str = "",
        user_id: Optional[int] = None,
        username: str = "",
    ) -> float:
        """Échange des points contre une récompense."""
        points = round(to_float(points), 2)
        if points <= 0:
            raise ValueError("Nombre de points invalide.")
        with session_scope() as session:
            account = cls._ensure_account(session, client_id)
            if float(account.points) < points:
                raise ValueError("Solde de points insuffisant.")
            account.points = float(account.points) - points
            session.add(
                CustomerPointsHistory(
                    client_id=client_id,
                    delta=-points,
                    balance_after=float(account.points),
                    reason="Échange récompense",
                    note=(note or "").strip(),
                    user_id=user_id,
                )
            )
            balance = float(account.points)
        audit_service.log_action(
            "Échange points",
            "CustomerPoints",
            f"client={client_id} points=-{points}",
            user_id,
            username,
        )
        return balance

    @staticmethod
    def history(client_id: int, limit: int = 200) -> List[CustomerPointsHistory]:
        with session_scope() as session:
            rows = session.scalars(
                select(CustomerPointsHistory)
                .where(CustomerPointsHistory.client_id == client_id)
                .order_by(CustomerPointsHistory.date.desc())
                .limit(limit)
            ).all()
            session.expunge_all()
            return list(rows)
