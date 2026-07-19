"""Contrôleur des ventes (module caisse) : création, historique, réimpression."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.product import Product
from app.models.sale import Payment, Sale, SaleItem
from app.models.stock import MOVEMENT_SALE, StockMovement
from app.utils.helpers import generate_ticket_number, to_float


@dataclass
class CartLine:
    """Ligne du panier de caisse (en mémoire, avant validation)."""

    product_id: Optional[int]
    name: str
    unit_price: float
    quantity: float
    purchase_price: float = 0.0

    @property
    def total(self) -> float:
        return round(self.unit_price * self.quantity, 2)


@dataclass
class PaymentLine:
    method: str
    amount: float


@dataclass
class SaleResult:
    """Résultat d'une vente validée (utilisé pour l'impression du ticket)."""

    sale_id: int
    ticket_number: str
    total: float
    amount_received: float
    change_due: float
    lines: List[CartLine] = field(default_factory=list)
    payments: List[PaymentLine] = field(default_factory=list)


class InsufficientPaymentError(Exception):
    """Levée lorsque le paiement ne couvre pas le total sans crédit autorisé."""


class SaleController:
    @staticmethod
    def _next_ticket_number(session) -> str:
        count = session.scalar(select(func.count()).select_from(Sale)) or 0
        return generate_ticket_number(count + 1)

    @classmethod
    def create_sale(
        cls,
        lines: List[CartLine],
        payments: List[PaymentLine],
        amount_received: float = 0,
        discount: float = 0,
        client_id: Optional[int] = None,
        user_id: Optional[int] = None,
        allow_credit: bool = False,
    ) -> SaleResult:
        """Enregistre une vente complète, met à jour le stock et les paiements.

        - ``amount_received`` : espèces remises par le client (pour la monnaie).
        - ``allow_credit`` : autorise un paiement partiel porté à la dette client.
        """
        if not lines:
            raise ValueError("Le panier est vide.")

        subtotal = round(sum(line.total for line in lines), 2)
        discount = max(0.0, to_float(discount))
        total = round(subtotal - discount, 2)
        paid = round(sum(to_float(p.amount) for p in payments), 2)

        if paid < total and not allow_credit:
            raise InsufficientPaymentError(
                f"Paiement insuffisant : {paid:,.0f} reçu pour un total de {total:,.0f}."
            )

        change_due = round(max(0.0, to_float(amount_received) - total), 2)
        profit = 0.0

        with session_scope() as session:
            ticket_number = cls._next_ticket_number(session)
            sale = Sale(
                ticket_number=ticket_number,
                date=datetime.now(),
                user_id=user_id,
                client_id=client_id,
                subtotal=subtotal,
                discount=discount,
                total=total,
                amount_received=to_float(amount_received),
                change_due=change_due,
                status="completed",
            )
            session.add(sale)
            session.flush()

            for line in lines:
                product = (
                    session.get(Product, line.product_id) if line.product_id else None
                )
                purchase_price = (
                    float(product.purchase_price) if product else line.purchase_price
                )
                profit += (line.unit_price - purchase_price) * line.quantity

                session.add(
                    SaleItem(
                        sale_id=sale.id,
                        product_id=line.product_id,
                        product_name=line.name,
                        unit_price=line.unit_price,
                        purchase_price=purchase_price,
                        quantity=line.quantity,
                        line_total=line.total,
                    )
                )

                if product:
                    before = float(product.quantity)
                    after = before - line.quantity
                    product.quantity = after
                    session.add(
                        StockMovement(
                            product_id=product.id,
                            movement_type=MOVEMENT_SALE,
                            quantity=line.quantity,
                            quantity_before=before,
                            quantity_after=after,
                            reason=f"Vente {ticket_number}",
                            user_id=user_id,
                        )
                    )

            for pay in payments:
                if to_float(pay.amount) != 0:
                    session.add(
                        Payment(
                            sale_id=sale.id,
                            method=pay.method,
                            amount=to_float(pay.amount),
                        )
                    )

            sale.profit = round(profit - discount, 2)

            # Crédit : la partie non payée est ajoutée à la dette du client.
            if paid < total and client_id:
                from app.models.client import Client

                client = session.get(Client, client_id)
                if client:
                    client.debt = float(client.debt) + (total - paid)

            session.flush()
            result = SaleResult(
                sale_id=sale.id,
                ticket_number=ticket_number,
                total=total,
                amount_received=to_float(amount_received),
                change_due=change_due,
                lines=list(lines),
                payments=[PaymentLine(p.method, to_float(p.amount)) for p in payments],
            )
        return result

    @staticmethod
    def get(sale_id: int) -> Optional[Sale]:
        with session_scope() as session:
            sale = session.scalar(
                select(Sale)
                .options(
                    joinedload(Sale.items),
                    joinedload(Sale.payments),
                    joinedload(Sale.user),
                    joinedload(Sale.client),
                )
                .where(Sale.id == sale_id)
            )
            if sale:
                session.expunge_all()
            return sale

    @staticmethod
    def list(
        search: str = "",
        start: Optional[date] = None,
        end: Optional[date] = None,
        limit: int = 500,
    ) -> List[Sale]:
        with session_scope() as session:
            query = select(Sale).options(
                joinedload(Sale.user),
                joinedload(Sale.client),
                joinedload(Sale.payments),
            )
            if search:
                query = query.where(Sale.ticket_number.ilike(f"%{search}%"))
            if start:
                query = query.where(Sale.date >= datetime.combine(start, datetime.min.time()))
            if end:
                query = query.where(Sale.date <= datetime.combine(end, datetime.max.time()))
            query = query.order_by(Sale.date.desc()).limit(limit)
            rows = session.scalars(query).unique().all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def cancel_sale(sale_id: int, restock: bool = True) -> None:
        """Annule une vente (réservé aux administrateurs) et restocke."""
        with session_scope() as session:
            sale = session.scalar(
                select(Sale).options(joinedload(Sale.items)).where(Sale.id == sale_id)
            )
            if not sale or sale.status == "cancelled":
                return
            if restock:
                for item in sale.items:
                    if item.product_id:
                        product = session.get(Product, item.product_id)
                        if product:
                            product.quantity = float(product.quantity) + float(
                                item.quantity
                            )
            sale.status = "cancelled"
