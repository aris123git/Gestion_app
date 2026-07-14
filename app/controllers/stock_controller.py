"""Contrôleur du stock (entrées, sorties, inventaire, corrections, historique)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.product import Product
from app.models.stock import (
    MOVEMENT_CORRECTION,
    MOVEMENT_IN,
    MOVEMENT_INVENTORY,
    MOVEMENT_OUT,
    StockMovement,
)
from app.utils.helpers import to_float


class StockController:
    @staticmethod
    def _record(
        session,
        product: Product,
        movement_type: str,
        new_quantity: float,
        reason: str,
        unit_cost: float,
        user_id: Optional[int],
    ) -> None:
        before = float(product.quantity)
        product.quantity = new_quantity
        session.add(
            StockMovement(
                product_id=product.id,
                movement_type=movement_type,
                quantity=abs(new_quantity - before),
                quantity_before=before,
                quantity_after=new_quantity,
                unit_cost=to_float(unit_cost),
                reason=reason,
                user_id=user_id,
            )
        )

    @classmethod
    def stock_in(
        cls,
        product_id: int,
        quantity: float,
        unit_cost: float = 0,
        reason: str = "",
        user_id: Optional[int] = None,
    ) -> None:
        quantity = to_float(quantity)
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return
            cls._record(
                session,
                product,
                MOVEMENT_IN,
                float(product.quantity) + quantity,
                reason or "Entrée de stock",
                unit_cost,
                user_id,
            )

    @classmethod
    def stock_out(
        cls,
        product_id: int,
        quantity: float,
        reason: str = "",
        user_id: Optional[int] = None,
    ) -> None:
        quantity = to_float(quantity)
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return
            cls._record(
                session,
                product,
                MOVEMENT_OUT,
                max(0.0, float(product.quantity) - quantity),
                reason or "Sortie de stock",
                0,
                user_id,
            )

    @classmethod
    def set_inventory(
        cls,
        product_id: int,
        counted_quantity: float,
        reason: str = "",
        user_id: Optional[int] = None,
    ) -> None:
        """Fixe la quantité réelle constatée lors d'un inventaire."""
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return
            cls._record(
                session,
                product,
                MOVEMENT_INVENTORY,
                to_float(counted_quantity),
                reason or "Inventaire",
                0,
                user_id,
            )

    @classmethod
    def correct(
        cls,
        product_id: int,
        new_quantity: float,
        reason: str = "",
        user_id: Optional[int] = None,
    ) -> None:
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return
            cls._record(
                session,
                product,
                MOVEMENT_CORRECTION,
                to_float(new_quantity),
                reason or "Correction",
                0,
                user_id,
            )

    @staticmethod
    def history(product_id: Optional[int] = None, limit: int = 500) -> List[StockMovement]:
        with session_scope() as session:
            query = select(StockMovement).options(joinedload(StockMovement.product))
            if product_id:
                query = query.where(StockMovement.product_id == product_id)
            query = query.order_by(StockMovement.date.desc()).limit(limit)
            rows = session.scalars(query).unique().all()
            session.expunge_all()
            return list(rows)
