"""Service d'historique des prix de vente."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.services import audit_service
from app.utils.helpers import to_float


class PriceHistoryService:
    @staticmethod
    def _margin(sale_price: float, purchase_price: float) -> float:
        return round(to_float(sale_price) - to_float(purchase_price), 2)

    @classmethod
    def record_change(
        cls,
        product_id: int,
        new_price: float,
        *,
        reason: str = "",
        user_id: Optional[int] = None,
        username: str = "",
        apply: bool = True,
    ) -> Optional[PriceHistory]:
        """Enregistre un changement de prix (et l'applique si ``apply``)."""
        new_price = to_float(new_price)
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return None
            old_price = float(product.sale_price)
            if abs(old_price - new_price) < 0.001:
                return None
            purchase = float(product.purchase_price)
            history = PriceHistory(
                product_id=product_id,
                old_price=old_price,
                new_price=new_price,
                old_margin=cls._margin(old_price, purchase),
                new_margin=cls._margin(new_price, purchase),
                user_id=user_id,
                reason=(reason or "").strip(),
            )
            session.add(history)
            if apply:
                product.sale_price = new_price
            session.flush()
            history_id = history.id
        audit_service.log_action(
            "Modification prix",
            "PriceHistory",
            f"product={product_id} {old_price}→{new_price} ({reason})",
            user_id,
            username,
        )
        return cls.get(history_id)

    @staticmethod
    def get(history_id: int) -> Optional[PriceHistory]:
        with session_scope() as session:
            row = session.get(PriceHistory, history_id)
            if row:
                session.expunge(row)
            return row

    @staticmethod
    def list_for_product(product_id: int, limit: int = 100) -> List[PriceHistory]:
        with session_scope() as session:
            rows = session.scalars(
                select(PriceHistory)
                .options(joinedload(PriceHistory.user))
                .where(PriceHistory.product_id == product_id)
                .order_by(PriceHistory.date.desc())
                .limit(limit)
            ).unique().all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def list_recent(limit: int = 200) -> List[PriceHistory]:
        with session_scope() as session:
            rows = session.scalars(
                select(PriceHistory)
                .options(
                    joinedload(PriceHistory.product),
                    joinedload(PriceHistory.user),
                )
                .order_by(PriceHistory.date.desc())
                .limit(limit)
            ).unique().all()
            session.expunge_all()
            return list(rows)
