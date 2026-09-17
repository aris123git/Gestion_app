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
    STATUS_SERVED,
    STATUS_UNPAID,
    OpenOrder,
    OpenOrderItem,
)

# Ouverte, servie ou non payée : encore modifiable / encaissable.
_ORDER_ACTIVE = frozenset({STATUS_OPEN, STATUS_SERVED, STATUS_UNPAID})
_ORDER_EDITABLE = _ORDER_ACTIVE
from app.services import table_service


class OrderService:
    @staticmethod
    def _public_id() -> str:
        return "CMD-" + secrets.token_hex(3).upper()

    @staticmethod
    def get(order_id: int) -> Optional[OpenOrder]:
        with session_scope() as session:
            order = session.scalars(
                select(OpenOrder)
                .options(
                    joinedload(OpenOrder.table),
                    joinedload(OpenOrder.items),
                    joinedload(OpenOrder.payments),
                )
                .where(OpenOrder.id == order_id)
            ).first()
            if order is None:
                return None
            session.expunge(order)
            return order

    @staticmethod
    def open_for_table(table_id: int) -> Optional[OpenOrder]:
        with session_scope() as session:
            order = session.scalars(
                select(OpenOrder)
                .options(joinedload(OpenOrder.items))
                .where(
                    OpenOrder.table_id == table_id,
                    OpenOrder.status.in_(tuple(_ORDER_ACTIVE)),
                )
                .order_by(OpenOrder.id.desc())
            ).first()
            if order is None:
                return None
            session.expunge(order)
            return order

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
                    .where(OpenOrder.status.in_(tuple(_ORDER_ACTIVE)))
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
    def create_from_cart(
        lines,
        *,
        table_id: Optional[int] = None,
        table_label: str = "",
        waitress_id: Optional[int] = None,
        waitress_name: str = "",
        opened_by: Optional[int] = None,
        mark_paid: bool = False,
        sale_id: Optional[int] = None,
    ) -> OpenOrder:
        """Enregistre une commande depuis le panier caisse (comme tablette)."""
        from app.models.dining_table import DiningTable

        with session_scope() as session:
            table = None
            if table_id:
                table = session.get(DiningTable, table_id)
                if table:
                    table.status = STATUS_OCCUPIED
            order = OpenOrder(
                public_id=OrderService._public_id(),
                table_id=table_id,
                table_label=(table_label or (table.display_name if table else "")),
                status=STATUS_PAID if mark_paid else STATUS_OPEN,
                waitress_id=waitress_id,
                waitress_name=(waitress_name or "").strip(),
                opened_by=opened_by,
                sale_id=sale_id,
            )
            if mark_paid:
                order.closed_at = datetime.utcnow()
            session.add(order)
            session.flush()
            total = 0.0
            for line in lines:
                qty = float(getattr(line, "quantity", 1) or 1)
                price = float(getattr(line, "unit_price", 0) or 0)
                lt = round(qty * price, 2)
                name = str(getattr(line, "name", "") or "")
                pid = getattr(line, "product_id", None)
                session.add(
                    OpenOrderItem(
                        order_id=order.id,
                        product_id=pid,
                        product_name=name,
                        quantity=qty,
                        unit_price=price,
                        line_total=lt,
                    )
                )
                total += lt
            order.total = total
            from app.services.maquis_order_service import consume_lines_stock

            consume_lines_stock(
                lines,
                public_id=order.public_id,
                user_id=opened_by,
                session=session,
            )
            if mark_paid:
                order.paid_amount = total
                if table_id and table:
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
    def append_cart_lines(
        order_id: int,
        lines,
        *,
        waitress_id: Optional[int] = None,
        waitress_name: str = "",
    ) -> OpenOrder:
        """Ajoute les lignes du panier à une commande existante (caisse PC)."""
        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order or order.status not in _ORDER_EDITABLE:
                raise ValueError("Commande non modifiable.")
            if waitress_id is not None:
                order.waitress_id = waitress_id
                order.waitress_name = (waitress_name or "").strip()
            for cart_line in lines:
                qty = float(getattr(cart_line, "quantity", 1) or 1)
                price = float(getattr(cart_line, "unit_price", 0) or 0)
                pid = getattr(cart_line, "product_id", None)
                name = str(getattr(cart_line, "name", "") or "")
                merged = False
                if pid and not getattr(cart_line, "free_amount", False):
                    for existing in order.items:
                        if existing.product_id == pid:
                            existing.quantity = float(existing.quantity or 0) + qty
                            existing.line_total = round(
                                float(existing.quantity) * float(existing.unit_price), 2
                            )
                            merged = True
                            break
                if not merged:
                    lt = round(qty * price, 2)
                    session.add(
                        OpenOrderItem(
                            order_id=order.id,
                            product_id=pid,
                            product_name=name,
                            quantity=qty,
                            unit_price=price,
                            line_total=lt,
                        )
                    )
            session.flush()
            order.total = round(
                sum(float(i.line_total or 0) for i in order.items), 2
            )
            from app.services.maquis_order_service import consume_lines_stock

            consume_lines_stock(
                lines,
                public_id=order.public_id,
                user_id=order.opened_by,
                session=session,
            )
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def upsert_cart_for_table(
        lines,
        *,
        table_id: Optional[int],
        table_label: str = "",
        waitress_id: Optional[int] = None,
        waitress_name: str = "",
        opened_by: Optional[int] = None,
    ) -> OpenOrder:
        """Crée ou complète la commande ouverte d'une table."""
        if table_id:
            existing = OrderService.open_for_table(table_id)
            if existing:
                return OrderService.append_cart_lines(
                    existing.id,
                    lines,
                    waitress_id=waitress_id,
                    waitress_name=waitress_name,
                )
        return OrderService.create_from_cart(
            lines,
            table_id=table_id,
            table_label=table_label,
            waitress_id=waitress_id,
            waitress_name=waitress_name,
            opened_by=opened_by,
            mark_paid=False,
        )

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
            if not order or order.status not in _ORDER_EDITABLE:
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
    def remove_item(item_id: int) -> OpenOrder:
        with session_scope() as session:
            line = session.get(OpenOrderItem, item_id)
            if not line:
                raise ValueError("Ligne introuvable.")
            order = session.get(OpenOrder, line.order_id)
            if not order or order.status not in _ORDER_EDITABLE:
                raise ValueError("Commande non modifiable.")
            order.total = float(order.total or 0) - float(line.line_total or 0)
            session.delete(line)
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def attach_sale_payment(
        order_id: int,
        sale_id: int,
        payments: list,
        *,
        user_id: Optional[int] = None,
        user_name: str = "",
    ) -> OpenOrder:
        from app.models.open_order_payment import OpenOrderPayment

        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order:
                raise ValueError("Commande introuvable.")
            paid = 0.0
            for pay in payments or []:
                amt = float(getattr(pay, "amount", 0) or 0)
                paid += amt
                session.add(
                    OpenOrderPayment(
                        order_id=order.id,
                        payment_mode=str(getattr(pay, "method", "Espèces") or "Espèces"),
                        amount=amt,
                        amount_tendered=float(getattr(pay, "amount_tendered", amt) or amt),
                        change_amount=0.0,
                        user_id=user_id,
                        user_name=user_name or "",
                    )
                )
            order.sale_id = sale_id
            order.paid_amount = round(float(order.paid_amount or 0) + paid, 2)
            total = float(order.total or 0)
            if order.paid_amount + 0.009 >= total:
                order.paid_amount = total
                order.status = STATUS_PAID
                order.closed_at = datetime.utcnow()
            else:
                order.status = STATUS_UNPAID
            from app.services import product_profile
            from app.services.maquis_order_service import _set_table_after_pay

            if product_profile.is_maquis():
                _set_table_after_pay(session, order)
            elif order.status == STATUS_PAID and order.table_id:
                from app.models.dining_table import DiningTable

                table = session.get(DiningTable, order.table_id)
                if table:
                    others = session.scalars(
                        select(OpenOrder).where(
                            OpenOrder.table_id == table.id,
                            OpenOrder.status.in_(tuple(_ORDER_ACTIVE)),
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
    def replace_items(order_id: int, lines: list) -> OpenOrder:
        """Remplace les lignes (admin) — comme updateOrderItems tablette."""
        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order or order.status not in _ORDER_EDITABLE:
                raise ValueError("Commande non modifiable.")
            from app.services.maquis_order_service import (
                consume_lines_stock,
                restore_order_stock,
            )

            restore_order_stock(order, user_id=order.opened_by, session=session)
            for old in list(order.items):
                session.delete(old)
            total = 0.0
            for line in lines:
                qty = float(line.get("quantity", 1))
                price = float(line.get("unit_price", 0))
                lt = round(qty * price, 2)
                session.add(
                    OpenOrderItem(
                        order_id=order.id,
                        product_id=line.get("product_id"),
                        product_name=str(line.get("product_name", "")),
                        quantity=qty,
                        unit_price=price,
                        line_total=lt,
                    )
                )
                total += lt
            order.total = total
            paid = float(order.paid_amount or 0)
            if paid <= 0:
                order.status = STATUS_OPEN
            elif paid + 0.009 < total:
                order.status = STATUS_UNPAID
            else:
                order.status = STATUS_PAID
            consume_lines_stock(
                lines,
                public_id=order.public_id,
                user_id=order.opened_by,
                session=session,
            )
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def mark_served(order_id: int) -> OpenOrder:
        """Marque la commande comme servie (parité tablette)."""
        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order:
                raise ValueError("Commande introuvable.")
            if order.status not in _ORDER_ACTIVE:
                raise ValueError("Commande déjà clôturée.")
            if order.status == STATUS_SERVED:
                session.expunge(order)
                return order
            order.status = STATUS_SERVED
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
                            OpenOrder.status.in_(tuple(_ORDER_ACTIVE)),
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
            from app.models.dining_table import DiningTable, STATUS_CLEANING
            from app.services.maquis_order_service import restore_order_stock

            restore_order_stock(order, user_id=order.opened_by, session=session)
            order.status = STATUS_CANCELLED
            order.closed_at = datetime.utcnow()
            if order.table_id:
                table = session.get(DiningTable, order.table_id)
                if table:
                    table.status = STATUS_CLEANING
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order
