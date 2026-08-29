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
from app.services import permissions as perms


class StockController:
    @staticmethod
    def _assert_user_can_manage(user_id: Optional[int]) -> None:
        """Contrôle côté serveur : le caissier ne peut pas bouger le stock."""
        if not user_id:
            return
        from app.models.user import User

        with session_scope() as session:
            user = session.get(User, user_id)
            if user is not None and not perms.can(user, perms.MANAGE_STOCK):
                raise ValueError(
                    "Vous n'avez pas l'autorisation de modifier le stock."
                )

    @staticmethod
    def _record(
        session,
        product: Product,
        movement_type: str,
        new_quantity: float,
        reason: str,
        unit_cost: float,
        user_id: Optional[int],
        *,
        supplier_id: Optional[int] = None,
        invoice_number: str = "",
        comment: str = "",
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
                comment=(comment or "").strip(),
                invoice_number=(invoice_number or "").strip(),
                supplier_id=supplier_id,
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
        *,
        supplier_id: Optional[int] = None,
        invoice_number: str = "",
        comment: str = "",
    ) -> None:
        quantity = to_float(quantity)
        unit_cost = to_float(unit_cost)
        cls._assert_user_can_manage(user_id)
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
                supplier_id=supplier_id,
                invoice_number=invoice_number,
                comment=comment,
            )
            # Le coût unitaire saisi lors de l'entrée met à jour le prix d'achat
            # du produit (dernier prix d'achat connu) — réservé aux rôles stock.
            if unit_cost > 0:
                product.purchase_price = unit_cost

    @classmethod
    def stock_out(
        cls,
        product_id: int,
        quantity: float,
        reason: str = "",
        user_id: Optional[int] = None,
        *,
        comment: str = "",
    ) -> None:
        quantity = to_float(quantity)
        if quantity <= 0:
            raise ValueError("Quantité invalide.")
        cls._assert_user_can_manage(user_id)
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return
            available = float(product.quantity)
            if quantity > available:
                raise ValueError(
                    f"Stock insuffisant : disponible {available:g}, demandé {quantity:g}."
                )
            cls._record(
                session,
                product,
                MOVEMENT_OUT,
                available - quantity,
                reason or "Sortie de stock",
                0,
                user_id,
                comment=comment,
            )

    @classmethod
    def set_inventory(
        cls,
        product_id: int,
        counted_quantity: float,
        reason: str = "",
        user_id: Optional[int] = None,
        *,
        comment: str = "",
    ) -> None:
        """Fixe la quantité réelle constatée lors d'un inventaire."""
        cls._assert_user_can_manage(user_id)
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
                comment=comment,
            )

    @classmethod
    def correct(
        cls,
        product_id: int,
        new_quantity: float,
        reason: str = "",
        user_id: Optional[int] = None,
        *,
        comment: str = "",
    ) -> None:
        """Ajustement de stock (correction d'erreur) — toujours tracé."""
        cls._assert_user_can_manage(user_id)
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return
            cls._record(
                session,
                product,
                MOVEMENT_CORRECTION,
                to_float(new_quantity),
                reason or "Ajustement / correction",
                0,
                user_id,
                comment=comment,
            )

    @staticmethod
    def history(product_id: Optional[int] = None, limit: int = 500) -> List[StockMovement]:
        with session_scope() as session:
            query = select(StockMovement).options(
                joinedload(StockMovement.product),
                joinedload(StockMovement.user),
                joinedload(StockMovement.supplier),
            )
            if product_id:
                query = query.where(StockMovement.product_id == product_id)
            query = query.order_by(StockMovement.date.desc()).limit(limit)
            rows = session.scalars(query).unique().all()
            session.expunge_all()
            return list(rows)
