"""Commandes ouvertes — Maquis Caisse PC.

Une commande ouverte est une ardoise de table : le serveur ajoute les articles
au fur et à mesure, sans déstocker. À l'encaissement, la commande devient une
vraie vente (``SaleController.create_sale``) : stock, bénéfices, tableau de
bord, dette client et session de caisse suivent alors le circuit normal.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Dict, List, Optional

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
from app.models.product import Product
from app.services import table_service


class OrderService:
    @staticmethod
    def _public_id() -> str:
        return "CMD-" + secrets.token_hex(3).upper()

    @staticmethod
    def _load(session, order_id: int) -> OpenOrder:
        order = session.get(OpenOrder, order_id)
        if not order:
            raise ValueError("Commande introuvable.")
        return order

    @staticmethod
    def _recompute_total(order: OpenOrder) -> float:
        total = round(sum(float(item.line_total or 0) for item in order.items), 2)
        order.total = total
        return total

    @staticmethod
    def _detach(session, order: OpenOrder) -> OpenOrder:
        session.flush()
        session.refresh(order)
        # Charge les relations avant de détacher (accès UI hors session).
        _ = [item.id for item in order.items]
        if order.table_id:
            _ = order.table
        session.expunge_all()
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
    def get(order_id: int) -> Optional[OpenOrder]:
        """Commande détachée, articles et table compris (lecture UI)."""
        with session_scope() as session:
            order = session.scalars(
                select(OpenOrder)
                .options(joinedload(OpenOrder.table), joinedload(OpenOrder.items))
                .where(OpenOrder.id == order_id)
            ).unique().one_or_none()
            if order is None:
                return None
            session.expunge_all()
            return order

    @staticmethod
    def open_for_table(table_id: int) -> List[OpenOrder]:
        """Commandes encore ouvertes sur une table (souvent une seule)."""
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(OpenOrder)
                    .options(joinedload(OpenOrder.table), joinedload(OpenOrder.items))
                    .where(
                        OpenOrder.table_id == table_id,
                        OpenOrder.status == STATUS_OPEN,
                    )
                    .order_by(OpenOrder.id.desc())
                )
                .unique()
                .all()
            )
            session.expunge_all()
            return rows

    @staticmethod
    def open_summary_by_table() -> Dict[int, dict]:
        """Résumé par table : total, nombre d'articles, ouverture la plus ancienne."""
        summary: Dict[int, dict] = {}
        for order in OrderService.list_open(limit=500):
            if not order.table_id:
                continue
            entry = summary.setdefault(
                int(order.table_id),
                {"total": 0.0, "items": 0.0, "orders": 0, "since": None},
            )
            entry["total"] += float(order.total or 0)
            entry["items"] += sum(float(i.quantity or 0) for i in order.items)
            entry["orders"] += 1
            opened = getattr(order, "created_at", None)
            if opened and (entry["since"] is None or opened < entry["since"]):
                entry["since"] = opened
        return summary

    @staticmethod
    def reserved_quantities(exclude_order_id: Optional[int] = None) -> Dict[int, float]:
        """Quantités déjà engagées par les commandes ouvertes, par produit.

        Exprimées en unités de stock (comme ``Product.quantity``) : une ligne au
        montant libre est ramenée au contenu du colis (``pack_content``).
        """
        reserved: Dict[int, float] = {}
        with session_scope() as session:
            rows = session.execute(
                select(
                    OpenOrderItem.product_id,
                    OpenOrderItem.quantity,
                    OpenOrderItem.free_amount,
                    Product.pack_content,
                )
                .join(OpenOrder, OpenOrder.id == OpenOrderItem.order_id)
                .join(Product, Product.id == OpenOrderItem.product_id, isouter=True)
                .where(OpenOrder.status == STATUS_OPEN)
            ).all()
        for product_id, quantity, free_amount, pack_content in rows:
            if not product_id:
                continue
            qty = float(quantity or 0)
            pack = float(pack_content or 0)
            if free_amount and pack > 0:
                qty = round(qty / pack, 6)
            reserved[int(product_id)] = reserved.get(int(product_id), 0.0) + qty
        if exclude_order_id is not None:
            for product_id, qty in OrderService._order_reserved(
                exclude_order_id
            ).items():
                remaining = reserved.get(product_id, 0.0) - qty
                if remaining <= 0.000001:
                    reserved.pop(product_id, None)
                else:
                    reserved[product_id] = remaining
        return reserved

    @staticmethod
    def _order_reserved(order_id: int) -> Dict[int, float]:
        reserved: Dict[int, float] = {}
        with session_scope() as session:
            rows = session.execute(
                select(
                    OpenOrderItem.product_id,
                    OpenOrderItem.quantity,
                    OpenOrderItem.free_amount,
                    Product.pack_content,
                )
                .join(Product, Product.id == OpenOrderItem.product_id, isouter=True)
                .where(OpenOrderItem.order_id == order_id)
            ).all()
        for product_id, quantity, free_amount, pack_content in rows:
            if not product_id:
                continue
            qty = float(quantity or 0)
            pack = float(pack_content or 0)
            if free_amount and pack > 0:
                qty = round(qty / pack, 6)
            reserved[int(product_id)] = reserved.get(int(product_id), 0.0) + qty
        return reserved

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
            return OrderService._detach(session, order)

    @staticmethod
    def add_item(
        order_id: int,
        *,
        product_id: Optional[int],
        product_name: str,
        quantity: float,
        unit_price: float,
        purchase_price: float = 0.0,
        free_amount: bool = False,
        amount: float = 0.0,
        note: str = "",
        merge: bool = True,
    ) -> OpenOrder:
        """Ajoute (ou cumule) une ligne sur la commande.

        ``merge`` regroupe avec une ligne identique déjà présente — comme la
        caisse, où un second clic sur le même produit incrémente la quantité.
        """
        with session_scope() as session:
            order = OrderService._load(session, order_id)
            if order.status != STATUS_OPEN:
                raise ValueError("Commande non modifiable.")
            qty = float(quantity)
            if qty <= 0:
                raise ValueError("La quantité doit être supérieure à zéro.")
            price = float(unit_price)
            line_total = (
                round(float(amount), 2) if free_amount else round(qty * price, 2)
            )
            existing = None
            if merge and not free_amount and product_id:
                for item in order.items:
                    if (
                        item.product_id == product_id
                        and not item.free_amount
                        and (item.note or "") == (note or "")
                        and abs(float(item.unit_price or 0) - price) < 0.001
                    ):
                        existing = item
                        break
            if existing is not None:
                existing.quantity = float(existing.quantity or 0) + qty
                existing.line_total = round(
                    float(existing.quantity) * float(existing.unit_price or 0), 2
                )
            else:
                session.add(
                    OpenOrderItem(
                        order_id=order.id,
                        product_id=product_id,
                        product_name=(product_name or "").strip(),
                        quantity=qty,
                        unit_price=price,
                        line_total=line_total,
                        purchase_price=float(purchase_price or 0),
                        free_amount=bool(free_amount),
                        note=(note or "").strip()[:200],
                    )
                )
            # Écrit avant le refresh : rafraîchir périme les objets et perdrait
            # les modifications encore en attente.
            session.flush()
            session.refresh(order)
            OrderService._recompute_total(order)
            return OrderService._detach(session, order)

    @staticmethod
    def set_item_quantity(order_id: int, item_id: int, quantity: float) -> OpenOrder:
        """Change la quantité d'une ligne (0 ou moins = suppression)."""
        with session_scope() as session:
            order = OrderService._load(session, order_id)
            if order.status != STATUS_OPEN:
                raise ValueError("Commande non modifiable.")
            item = session.get(OpenOrderItem, item_id)
            if not item or item.order_id != order.id:
                raise ValueError("Ligne introuvable.")
            qty = float(quantity)
            if qty <= 0:
                session.delete(item)
            elif item.free_amount:
                raise ValueError(
                    "Ligne au montant libre : supprimez-la puis ressaisissez "
                    "le montant."
                )
            else:
                item.quantity = qty
                item.line_total = round(qty * float(item.unit_price or 0), 2)
            session.flush()
            session.refresh(order)
            OrderService._recompute_total(order)
            return OrderService._detach(session, order)

    @staticmethod
    def remove_item(order_id: int, item_id: int) -> OpenOrder:
        return OrderService.set_item_quantity(order_id, item_id, 0)

    @staticmethod
    def set_item_note(order_id: int, item_id: int, note: str) -> OpenOrder:
        with session_scope() as session:
            order = OrderService._load(session, order_id)
            if order.status != STATUS_OPEN:
                raise ValueError("Commande non modifiable.")
            item = session.get(OpenOrderItem, item_id)
            if not item or item.order_id != order.id:
                raise ValueError("Ligne introuvable.")
            item.note = (note or "").strip()[:200]
            return OrderService._detach(session, order)

    @staticmethod
    def update_order(
        order_id: int,
        *,
        customer_name: Optional[str] = None,
        note: Optional[str] = None,
    ) -> OpenOrder:
        with session_scope() as session:
            order = OrderService._load(session, order_id)
            if customer_name is not None:
                order.customer_name = customer_name.strip()[:200]
            if note is not None:
                order.note = note.strip()
            return OrderService._detach(session, order)

    @staticmethod
    def transfer_to_table(order_id: int, table_id: int) -> OpenOrder:
        """Déplace une commande vers une autre table (client qui change de place)."""
        from app.models.dining_table import DiningTable

        with session_scope() as session:
            order = OrderService._load(session, order_id)
            if order.status != STATUS_OPEN:
                raise ValueError("Seule une commande ouverte peut être transférée.")
            target = session.get(DiningTable, table_id)
            if not target:
                raise ValueError("Table de destination introuvable.")
            previous_id = order.table_id
            if previous_id == table_id:
                return OrderService._detach(session, order)
            order.table_id = table_id
            target.status = STATUS_OCCUPIED
            session.flush()
            if previous_id:
                OrderService._release_table_if_empty(session, previous_id, order.id)
            return OrderService._detach(session, order)

    @staticmethod
    def _release_table_if_empty(session, table_id: int, order_id: int) -> None:
        """Libère la table s'il n'y reste aucune commande ouverte."""
        from app.models.dining_table import DiningTable

        table = session.get(DiningTable, table_id)
        if not table:
            return
        others = session.scalars(
            select(OpenOrder).where(
                OpenOrder.table_id == table_id,
                OpenOrder.status == STATUS_OPEN,
                OpenOrder.id != order_id,
            )
        ).first()
        if others is None:
            table.status = STATUS_FREE

    @staticmethod
    def cart_lines(order_id: int) -> list:
        """Traduit les lignes de la commande en lignes de panier caisse."""
        from app.controllers.product_controller import ProductController
        from app.controllers.sale_controller import CartLine

        order = OrderService.get(order_id)
        if not order:
            raise ValueError("Commande introuvable.")
        lines = []
        for item in order.items:
            pack_content = 0.0
            purchase_price = float(item.purchase_price or 0)
            if item.product_id:
                product = ProductController.get(item.product_id)
                if product is not None:
                    pack_content = float(getattr(product, "pack_content", 0) or 0)
                    if purchase_price <= 0:
                        purchase_price = float(product.purchase_price or 0)
            lines.append(
                CartLine(
                    product_id=item.product_id,
                    name=item.product_name,
                    unit_price=float(item.unit_price or 0),
                    quantity=float(item.quantity or 0),
                    purchase_price=purchase_price,
                    free_amount=bool(item.free_amount),
                    amount=float(item.line_total or 0) if item.free_amount else 0.0,
                    pack_content=pack_content,
                )
            )
        return lines

    @staticmethod
    def checkout(
        order_id: int,
        *,
        payments: Optional[list] = None,
        amount_received: float = 0,
        discount: float = 0,
        client_id: Optional[int] = None,
        user_id: Optional[int] = None,
        allow_credit: bool = False,
        debt_due_date=None,
    ):
        """Encaisse la commande : crée la vente puis solde la commande.

        Retourne le ``SaleResult`` de la vente (None si commande vide).
        Aucune impression n'est déclenchée ici — le ticket reste à la demande.
        """
        from app.controllers.sale_controller import PaymentLine, SaleController

        lines = OrderService.cart_lines(order_id)
        if not lines:
            OrderService.mark_paid(order_id)
            return None
        subtotal = round(sum(line.total for line in lines), 2)
        discount = max(0.0, min(float(discount or 0), subtotal))
        total = round(subtotal - discount, 2)
        if payments is None:
            payments = [PaymentLine(method="Espèces", amount=total)]
            amount_received = amount_received or total
        result = SaleController.create_sale(
            lines=lines,
            payments=payments,
            amount_received=amount_received,
            discount=discount,
            client_id=client_id,
            user_id=user_id,
            allow_credit=allow_credit,
            debt_due_date=debt_due_date,
        )
        OrderService.mark_paid(order_id, sale_id=result.sale_id)
        from app.services import audit_service

        audit_service.log_action(
            "Encaissement commande",
            "OpenOrder",
            f"commande={order_id} vente={result.ticket_number} total={result.total}",
            user_id,
            "",
        )
        return result

    @staticmethod
    def mark_paid(order_id: int, sale_id: Optional[int] = None) -> OpenOrder:
        with session_scope() as session:
            order = OrderService._load(session, order_id)
            order.status = STATUS_PAID
            order.closed_at = datetime.now()
            if sale_id is not None:
                order.sale_id = int(sale_id)
            if order.table_id:
                # Libère si plus d'autres commandes ouvertes sur la table.
                OrderService._release_table_if_empty(
                    session, order.table_id, order.id
                )
            return OrderService._detach(session, order)

    @staticmethod
    def cancel(order_id: int) -> OpenOrder:
        with session_scope() as session:
            order = OrderService._load(session, order_id)
            order.status = STATUS_CANCELLED
            order.closed_at = datetime.now()
            if order.table_id:
                OrderService._release_table_if_empty(
                    session, order.table_id, order.id
                )
            return OrderService._detach(session, order)


__all__ = ["OrderService", "table_service"]
