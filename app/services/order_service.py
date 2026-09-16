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
    def get(order_id: int) -> Optional[OpenOrder]:
        with session_scope() as session:
            order = session.scalar(
                select(OpenOrder)
                .options(joinedload(OpenOrder.table), joinedload(OpenOrder.items))
                .where(OpenOrder.id == order_id)
            )
            if order:
                session.expunge(order)
            return order

    @staticmethod
    def get_open_for_table(table_id: int) -> Optional[OpenOrder]:
        """Commande ouverte la plus récente d'une table (ou None)."""
        with session_scope() as session:
            order = session.scalar(
                select(OpenOrder)
                .options(joinedload(OpenOrder.table), joinedload(OpenOrder.items))
                .where(
                    OpenOrder.table_id == table_id,
                    OpenOrder.status == STATUS_OPEN,
                )
                .order_by(OpenOrder.id.desc())
            )
            if order:
                session.expunge(order)
            return order

    @staticmethod
    def _recompute_total(session, order: OpenOrder) -> None:
        order.total = round(
            sum(float(item.line_total or 0) for item in order.items), 2
        )

    @staticmethod
    def add_product(order_id: int, product_id: int, quantity: float = 1.0) -> OpenOrder:
        """Ajoute un produit catalogue (ou augmente sa quantité) avec contrôle stock."""
        from app.models.product import Product

        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order or order.status != STATUS_OPEN:
                raise ValueError("Commande non modifiable.")
            product = session.get(Product, product_id)
            if not product:
                raise ValueError("Produit introuvable.")
            qty = float(quantity)
            if qty <= 0:
                raise ValueError("Quantité invalide.")
            line = next(
                (
                    item
                    for item in order.items
                    if item.product_id == product_id
                ),
                None,
            )
            current = float(line.quantity) if line is not None else 0.0
            available = float(product.quantity or 0)
            if current + qty > available + 0.0001:
                raise ValueError(
                    f"Stock insuffisant pour « {product.name} » : "
                    f"disponible {available:g}, demandé {current + qty:g}."
                )
            if line is not None:
                line.quantity = current + qty
                line.line_total = round(
                    float(line.quantity) * float(line.unit_price), 2
                )
            else:
                line = OpenOrderItem(
                    order_id=order.id,
                    product_id=product_id,
                    product_name=product.name,
                    quantity=qty,
                    unit_price=float(product.sale_price or 0),
                    line_total=round(qty * float(product.sale_price or 0), 2),
                )
                session.add(line)
            session.flush()
            session.refresh(order)
            OrderService._recompute_total(session, order)
        return OrderService.get(order_id)

    @staticmethod
    def set_item_quantity(order_id: int, item_id: int, quantity: float) -> OpenOrder:
        """Fixe la quantité d'une ligne (0 = suppression), avec contrôle stock."""
        from app.models.product import Product

        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order or order.status != STATUS_OPEN:
                raise ValueError("Commande non modifiable.")
            line = session.get(OpenOrderItem, item_id)
            if not line or line.order_id != order.id:
                raise ValueError("Article de commande introuvable.")
            qty = float(quantity)
            if qty <= 0:
                session.delete(line)
            else:
                if line.product_id:
                    product = session.get(Product, line.product_id)
                    if product and qty > float(product.quantity or 0) + 0.0001:
                        raise ValueError(
                            f"Stock insuffisant pour « {product.name} » : "
                            f"disponible {float(product.quantity or 0):g}, "
                            f"demandé {qty:g}."
                        )
                line.quantity = qty
                line.line_total = round(qty * float(line.unit_price), 2)
            session.flush()
            session.refresh(order)
            OrderService._recompute_total(session, order)
        return OrderService.get(order_id)

    @staticmethod
    def remove_item(order_id: int, item_id: int) -> OpenOrder:
        return OrderService.set_item_quantity(order_id, item_id, 0)

    @staticmethod
    def settle(order_id: int, user_id: Optional[int] = None):
        """Encaisse la commande : enregistre une vraie vente (stock, rapports)
        puis marque la commande payée et libère la table.

        Aucune impression : le ticket n'est ni imprimé ni proposé — le caissier
        peut le réimprimer depuis Rapports s'il en a vraiment besoin.
        """
        from app.controllers.sale_controller import (
            CartLine,
            PaymentLine,
            SaleController,
        )
        from app.models.product import Product

        order = OrderService.get(order_id)
        if not order:
            raise ValueError("Commande introuvable.")
        if order.status != STATUS_OPEN:
            raise ValueError("Commande déjà clôturée.")
        if not order.items:
            raise ValueError("Commande vide : ajoutez au moins un article.")

        lines: list[CartLine] = []
        with session_scope() as session:
            for item in order.items:
                purchase_price = 0.0
                free_amount = False
                pack_content = 0.0
                if item.product_id:
                    product = session.get(Product, item.product_id)
                    if product:
                        free_amount = bool(
                            getattr(product, "free_amount_sale", False)
                        )
                        pack_content = float(
                            getattr(product, "pack_content", 0) or 0
                        )
                        purchase_price = (
                            float(product.cost_per_sale_unit)
                            if free_amount
                            else float(product.purchase_price or 0)
                        )
                lines.append(
                    CartLine(
                        product_id=item.product_id,
                        name=item.product_name,
                        unit_price=float(item.unit_price or 0),
                        quantity=float(item.quantity or 0),
                        purchase_price=purchase_price,
                        free_amount=free_amount,
                        amount=float(item.line_total or 0) if free_amount else 0.0,
                        pack_content=pack_content,
                    )
                )

        total = round(sum(line.total for line in lines), 2)
        result = SaleController.create_sale(
            lines=lines,
            payments=[PaymentLine("Espèces", total)],
            amount_received=total,
            user_id=user_id,
        )
        OrderService.mark_paid(order_id)
        return result

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
