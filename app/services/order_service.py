"""Commandes ouvertes — Maquis Caisse PC.

Le service porte la logique métier des commandes de table : ouverture depuis
la salle, ajout / modification / retrait des lignes depuis l'écran caisse
tablette, remise éventuelle, encaissement (« Marquer payée » sans impression
automatique) et annulation. Les tables sont libérées automatiquement dès
qu'il n'y a plus de commande ouverte dessus.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.dining_table import STATUS_FREE, STATUS_OCCUPIED
from app.models.open_order import (
    STATUS_CANCELLED,
    STATUS_OPEN,
    STATUS_PAID,
    OpenOrder,
    OpenOrderItem,
)
from app.services import table_service


class OrderService:
    @staticmethod
    def _public_id() -> str:
        return "CMD-" + secrets.token_hex(3).upper()

    @staticmethod
    def list_open(limit: int = 100) -> List[OpenOrder]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(OpenOrder)
                    .options(
                        joinedload(OpenOrder.table),
                        joinedload(OpenOrder.items),
                    )
                    .where(OpenOrder.status == STATUS_OPEN)
                    .order_by(OpenOrder.id.desc())
                    .limit(limit)
                )
                .unique()
                .all()
            )
            for row in rows:
                session.expunge(row)
            return rows

    @staticmethod
    def list_recent(limit: int = 80) -> List[OpenOrder]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(OpenOrder)
                    .options(joinedload(OpenOrder.table), joinedload(OpenOrder.items))
                    .order_by(OpenOrder.id.desc())
                    .limit(limit)
                )
                .unique()
                .all()
            )
            for row in rows:
                session.expunge(row)
            return rows

    @staticmethod
    def open_on_table(
        table_id: int,
        *,
        customer_name: str = "",
        opened_by: Optional[int] = None,
    ) -> OpenOrder:
        from app.models.dining_table import DiningTable

        with session_scope() as session:
            table = session.get(DiningTable, table_id)
            if not table:
                raise ValueError("Table introuvable.")
            order = OpenOrder(
                public_id=OrderService._public_id(),
                table_id=table_id,
                status=STATUS_OPEN,
                customer_name=(customer_name or "").strip(),
                opened_by=opened_by,
            )
            table.status = STATUS_OCCUPIED
            session.add(order)
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def get(order_id: int) -> Optional[OpenOrder]:
        """Recharge une commande avec ses lignes et sa table (session détachée)."""
        with session_scope() as session:
            order = session.scalars(
                select(OpenOrder)
                .options(
                    joinedload(OpenOrder.table),
                    joinedload(OpenOrder.items),
                )
                .where(OpenOrder.id == order_id)
            ).unique().one_or_none()
            if order is not None:
                session.expunge(order)
            return order

    @staticmethod
    def _recompute_total(order: OpenOrder) -> None:
        subtotal = sum(float(l.line_total or 0) for l in order.items)
        order.total = round(max(0.0, subtotal), 2)

    @staticmethod
    def add_item(
        order_id: int,
        *,
        product_id: Optional[int],
        product_name: str,
        quantity: float,
        unit_price: float,
        merge: bool = True,
    ) -> OpenOrder:
        """Ajoute une ligne. Si ``merge`` et qu'une ligne identique existe déjà
        (même produit et même prix unitaire), on incrémente sa quantité pour
        éviter les doublons visuels dans le panier tablette."""
        with session_scope() as session:
            order = session.scalars(
                select(OpenOrder)
                .options(joinedload(OpenOrder.items))
                .where(OpenOrder.id == order_id)
            ).unique().one_or_none()
            if not order or order.status != STATUS_OPEN:
                raise ValueError("Commande non modifiable.")
            qty = float(quantity)
            if qty <= 0:
                raise ValueError("Quantité invalide.")
            price = float(unit_price)
            if price < 0:
                raise ValueError("Prix invalide.")
            merged = False
            if merge and product_id is not None:
                for line in order.items:
                    if line.product_id == product_id and float(line.unit_price) == price:
                        line.quantity = float(line.quantity or 0) + qty
                        line.line_total = round(float(line.quantity) * price, 2)
                        merged = True
                        break
            if not merged:
                order.items.append(
                    OpenOrderItem(
                        order_id=order.id,
                        product_id=product_id,
                        product_name=(product_name or "").strip(),
                        quantity=qty,
                        unit_price=price,
                        line_total=round(qty * price, 2),
                    )
                )
            OrderService._recompute_total(order)
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def update_item_quantity(order_id: int, item_id: int, quantity: float) -> OpenOrder:
        """Change la quantité d'une ligne (retire la ligne si ``quantity <= 0``)."""
        with session_scope() as session:
            order = session.scalars(
                select(OpenOrder)
                .options(joinedload(OpenOrder.items))
                .where(OpenOrder.id == order_id)
            ).unique().one_or_none()
            if not order or order.status != STATUS_OPEN:
                raise ValueError("Commande non modifiable.")
            target = next((l for l in order.items if l.id == item_id), None)
            if target is None:
                raise ValueError("Ligne introuvable.")
            qty = float(quantity)
            if qty <= 0:
                order.items.remove(target)
                session.delete(target)
            else:
                target.quantity = qty
                target.line_total = round(qty * float(target.unit_price or 0), 2)
            OrderService._recompute_total(order)
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def remove_item(order_id: int, item_id: int) -> OpenOrder:
        return OrderService.update_item_quantity(order_id, item_id, 0)

    @staticmethod
    def set_customer_name(order_id: int, customer_name: str) -> OpenOrder:
        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order or order.status != STATUS_OPEN:
                raise ValueError("Commande non modifiable.")
            order.customer_name = (customer_name or "").strip()
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def set_note(order_id: int, note: str) -> OpenOrder:
        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order or order.status != STATUS_OPEN:
                raise ValueError("Commande non modifiable.")
            order.note = (note or "").strip()
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def mark_paid(order_id: int) -> OpenOrder:
        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order:
                raise ValueError("Commande introuvable.")
            order.status = STATUS_PAID
            order.closed_at = datetime.utcnow()
            if order.table_id:
                from app.models.dining_table import DiningTable

                table = session.get(DiningTable, order.table_id)
                if table:
                    # Libère si plus d'autres commandes ouvertes sur la table.
                    others = session.scalars(
                        select(OpenOrder).where(
                            OpenOrder.table_id == table.id,
                            OpenOrder.status == STATUS_OPEN,
                            OpenOrder.id != order.id,
                        )
                    ).first()
                    if others is None:
                        table.status = STATUS_FREE
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def cancel(order_id: int) -> OpenOrder:
        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order:
                raise ValueError("Commande introuvable.")
            order.status = STATUS_CANCELLED
            order.closed_at = datetime.utcnow()
            if order.table_id:
                from app.models.dining_table import DiningTable

                table = session.get(DiningTable, order.table_id)
                if table:
                    others = session.scalars(
                        select(OpenOrder).where(
                            OpenOrder.table_id == table.id,
                            OpenOrder.status == STATUS_OPEN,
                            OpenOrder.id != order.id,
                        )
                    ).first()
                    if others is None:
                        table.status = STATUS_FREE
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order
