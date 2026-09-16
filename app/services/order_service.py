"""Commandes ouvertes — Maquis Caisse PC."""

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
    def add_item(
        order_id: int,
        *,
        product_id: Optional[int],
        product_name: str,
        quantity: float,
        unit_price: float,
    ) -> OpenOrder:
        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order or order.status != STATUS_OPEN:
                raise ValueError("Commande non modifiable.")
            qty = float(quantity)
            price = float(unit_price)
            line = OpenOrderItem(
                order_id=order.id,
                product_id=product_id,
                product_name=(product_name or "").strip(),
                quantity=qty,
                unit_price=price,
                line_total=round(qty * price, 2),
            )
            session.add(line)
            order.total = float(order.total or 0) + float(line.line_total)
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def create_from_cart(
        lines: list,
        *,
        table_id: Optional[int] = None,
        customer_name: str = "",
        opened_by: Optional[int] = None,
        note: str = "",
    ) -> OpenOrder:
        """Enregistre une commande ouverte depuis le panier caisse (comme tablette).

        Ne marque pas comme payée et n'imprime pas — l'impression éventuelle
        se fait à l'enregistrement côté UI si l'option est activée.
        """
        if not lines:
            raise ValueError("Panier vide.")
        from app.models.dining_table import STATUS_OCCUPIED, DiningTable

        with session_scope() as session:
            table = None
            if table_id:
                table = session.get(DiningTable, table_id)
                if not table:
                    raise ValueError("Table introuvable.")
            order = OpenOrder(
                public_id=OrderService._public_id(),
                table_id=table_id,
                status=STATUS_OPEN,
                customer_name=(customer_name or "").strip(),
                note=(note or "").strip(),
                opened_by=opened_by,
                total=0,
            )
            session.add(order)
            session.flush()
            total = 0.0
            for line in lines:
                qty = float(getattr(line, "quantity", 0) or 0)
                if qty <= 0:
                    continue
                if getattr(line, "free_amount", False):
                    line_total = round(float(getattr(line, "amount", 0) or 0), 2)
                    price = float(getattr(line, "unit_price", 0) or 0)
                else:
                    price = float(getattr(line, "unit_price", 0) or 0)
                    line_total = round(qty * price, 2)
                item = OpenOrderItem(
                    order_id=order.id,
                    product_id=getattr(line, "product_id", None),
                    product_name=(getattr(line, "name", "") or "").strip(),
                    quantity=qty,
                    unit_price=price,
                    line_total=line_total,
                )
                session.add(item)
                total += line_total
            if total <= 0:
                raise ValueError("Panier vide.")
            order.total = total
            if table is not None:
                table.status = STATUS_OCCUPIED
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
