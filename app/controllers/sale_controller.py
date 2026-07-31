"""Contrôleur des ventes (module caisse) : création, historique, réimpression."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app import config
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


class InsufficientStockError(Exception):
    """Levée lorsqu'une vente dépasserait le stock disponible."""


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
        - ``allow_credit`` : autorise un paiement partiel / total porté à la dette
          client (méthode ``PAYMENT_METHOD_CREDIT`` / « Dette » sur le ticket).
        """
        if not lines:
            raise ValueError("Le panier est vide.")

        subtotal = round(sum(line.total for line in lines), 2)
        discount = max(0.0, to_float(discount))
        total = round(subtotal - discount, 2)

        credit_method = config.PAYMENT_METHOD_CREDIT
        cash_paid = round(
            sum(
                to_float(p.amount)
                for p in payments
                if p.method != credit_method
            ),
            2,
        )
        credit_marked = round(
            sum(
                to_float(p.amount)
                for p in payments
                if p.method == credit_method
            ),
            2,
        )
        covered = round(cash_paid + credit_marked, 2)

        if covered < total and not allow_credit:
            raise InsufficientPaymentError(
                f"Paiement insuffisant : {cash_paid:,.0f} reçu pour un total de {total:,.0f}."
            )
        if credit_marked > 0 and not client_id:
            raise ValueError(
                "Impossible de porter une vente en dette sans client sélectionné."
            )
        if covered < total and allow_credit and client_id:
            # Reste non saisi → complété automatiquement en dette (ticket).
            credit_marked = round(total - cash_paid, 2)

        # Montant réellement porté au ledger dette (= non encaissé).
        credit_amount = round(max(0.0, total - cash_paid), 2)
        if credit_amount > 0 and not client_id:
            raise InsufficientPaymentError(
                f"Paiement insuffisant : {cash_paid:,.0f} reçu pour un total de {total:,.0f}."
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

            # Vérifie le stock avant toute sortie (agrège les lignes du même produit).
            required: dict[int, float] = {}
            for line in lines:
                if line.product_id:
                    required[line.product_id] = (
                        required.get(line.product_id, 0.0) + float(line.quantity)
                    )
            for product_id, needed in required.items():
                product = session.get(Product, product_id)
                if product is None:
                    continue
                available = float(product.quantity)
                if available <= 0 or available < needed:
                    raise InsufficientStockError(
                        f"Stock insuffisant pour « {product.name} » : "
                        f"disponible {available:g}, demandé {needed:g}."
                    )

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

            # Paiements encaissés (hors dette) + ligne « Dette » pour le ticket.
            stored_payments: List[PaymentLine] = []
            for pay in payments:
                amount = to_float(pay.amount)
                if amount == 0 or pay.method == credit_method:
                    continue
                session.add(
                    Payment(
                        sale_id=sale.id,
                        method=pay.method,
                        amount=amount,
                    )
                )
                stored_payments.append(PaymentLine(pay.method, amount))

            if credit_amount > 0:
                session.add(
                    Payment(
                        sale_id=sale.id,
                        method=credit_method,
                        amount=credit_amount,
                    )
                )
                stored_payments.append(PaymentLine(credit_method, credit_amount))

            sale.profit = round(profit - discount, 2)

            # Crédit : crée une dette (ledger) et synchronise le cache Client.debt.
            if credit_amount > 0 and client_id:
                from app.services.debt_service import DebtService

                DebtService.create_debt(
                    client_id,
                    credit_amount,
                    sale_id=sale.id,
                    note=f"Crédit vente {ticket_number}",
                    user_id=user_id,
                    session=session,
                )

            session.flush()
            result = SaleResult(
                sale_id=sale.id,
                ticket_number=ticket_number,
                total=total,
                amount_received=to_float(amount_received),
                change_due=change_due,
                lines=list(lines),
                payments=stored_payments,
            )

        if credit_amount > 0 and client_id:
            from app.services import audit_service

            audit_service.log_action(
                "Création dette",
                "Debt",
                f"client={client_id} montant={credit_amount} sale={result.sale_id}",
                user_id,
                "",
            )

        # Fidélité + CRM
        if client_id:
            from app.services.customer_service import CustomerService
            from app.services.loyalty_service import LoyaltyService

            LoyaltyService.add_points_for_sale(
                client_id, result.total, sale_id=result.sale_id, user_id=user_id
            )
            CustomerService.mark_visit(client_id)
        return result

    # --- Ventes en attente (Sprint 5) --------------------------------------
    @classmethod
    def hold_sale(
        cls,
        lines: List[CartLine],
        *,
        discount: float = 0,
        client_id: Optional[int] = None,
        user_id: Optional[int] = None,
        note: str = "",
    ) -> Sale:
        """Met une vente en attente (sans déstocker ni encaisser)."""
        if not lines:
            raise ValueError("Le panier est vide.")
        subtotal = round(sum(line.total for line in lines), 2)
        discount = max(0.0, to_float(discount))
        total = round(subtotal - discount, 2)
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
                amount_received=0,
                change_due=0,
                status="pending",
            )
            session.add(sale)
            session.flush()
            for line in lines:
                session.add(
                    SaleItem(
                        sale_id=sale.id,
                        product_id=line.product_id,
                        product_name=line.name,
                        unit_price=line.unit_price,
                        purchase_price=line.purchase_price,
                        quantity=line.quantity,
                        line_total=line.total,
                    )
                )
            sale_id = sale.id
        from app.services import audit_service

        audit_service.log_action(
            "Vente en attente",
            "Sale",
            f"{ticket_number} {note}".strip(),
            user_id,
            "",
        )
        return cls.get(sale_id)  # type: ignore[return-value]

    @staticmethod
    def list_pending(limit: int = 100) -> List[Sale]:
        with session_scope() as session:
            rows = session.scalars(
                select(Sale)
                .options(joinedload(Sale.items), joinedload(Sale.client))
                .where(Sale.status == "pending")
                .order_by(Sale.date.desc())
                .limit(limit)
            ).unique().all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def pending_to_cart(sale_id: int) -> tuple[List[CartLine], float, Optional[int]]:
        """Retourne (lignes, remise, client_id) d'une vente en attente."""
        sale = SaleController.get(sale_id)
        if not sale or sale.status != "pending":
            raise ValueError("Vente en attente introuvable.")
        lines = [
            CartLine(
                product_id=item.product_id,
                name=item.product_name,
                unit_price=float(item.unit_price),
                quantity=float(item.quantity),
                purchase_price=float(item.purchase_price),
            )
            for item in sale.items
        ]
        return lines, float(sale.discount), sale.client_id

    @staticmethod
    def delete_pending(sale_id: int, user_id: Optional[int] = None) -> None:
        with session_scope() as session:
            sale = session.scalar(
                select(Sale)
                .options(joinedload(Sale.items), joinedload(Sale.payments))
                .where(Sale.id == sale_id)
            )
            if not sale or sale.status != "pending":
                return
            session.delete(sale)
        from app.services import audit_service

        audit_service.log_action(
            "Suppression vente en attente", "Sale", str(sale_id), user_id, ""
        )

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
    def cancel_sale(
        sale_id: int,
        restock: bool = True,
        user_id: Optional[int] = None,
        username: str = "",
    ) -> None:
        """Annule une vente, restocke et annule les dettes liées."""
        cancelled_debts = 0
        with session_scope() as session:
            sale = session.scalar(
                select(Sale).options(joinedload(Sale.items)).where(Sale.id == sale_id)
            )
            if not sale or sale.status == "cancelled":
                return
            # Les ventes « pending » n'ont jamais déstocké.
            if restock and sale.status == "completed":
                for item in sale.items:
                    if item.product_id:
                        product = session.get(Product, item.product_id)
                        if product:
                            product.quantity = float(product.quantity) + float(
                                item.quantity
                            )
            from app.services.debt_service import DebtService

            cancelled_debts = DebtService.cancel_debts_for_sale(
                sale_id,
                user_id=user_id,
                username=username,
                session=session,
            )
            sale.status = "cancelled"
        if cancelled_debts:
            from app.services import audit_service

            audit_service.log_action(
                "Annulation dette",
                "Debt",
                f"sale={sale_id} dettes_annulées={cancelled_debts}",
                user_id,
                username,
            )
