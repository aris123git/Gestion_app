"""Service des achats / réceptions fournisseurs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseItem
from app.models.stock import MOVEMENT_IN, StockMovement
from app.services import audit_service
from app.services.supplier_debt_service import SupplierDebtService
from app.utils.helpers import to_float


@dataclass
class PurchaseLine:
    product_id: Optional[int]
    name: str
    quantity: float
    unit_cost: float

    @property
    def total(self) -> float:
        return round(to_float(self.quantity) * to_float(self.unit_cost), 2)


class PurchaseService:
    """Enregistre un achat, met à jour le stock et crée une dette si besoin."""

    @classmethod
    def create(
        cls,
        lines: List[PurchaseLine],
        *,
        supplier_id: Optional[int] = None,
        invoice_number: str = "",
        amount_paid: float = 0,
        discount: float = 0,
        note: str = "",
        user_id: Optional[int] = None,
        username: str = "",
    ) -> Purchase:
        if not lines:
            raise ValueError("Aucune ligne d'achat.")
        subtotal = round(sum(line.total for line in lines), 2)
        discount = max(0.0, to_float(discount))
        total = round(max(0.0, subtotal - discount), 2)
        amount_paid = round(to_float(amount_paid), 2)
        if amount_paid < 0:
            raise ValueError("Montant payé invalide.")
        if amount_paid < total and not supplier_id:
            raise ValueError(
                "Un achat partiellement payé doit être rattaché à un fournisseur."
            )

        with session_scope() as session:
            purchase = Purchase(
                supplier_id=supplier_id,
                date=datetime.now(),
                invoice_number=(invoice_number or "").strip(),
                subtotal=subtotal,
                discount=discount,
                total=total,
                amount_paid=min(amount_paid, total),
                status="completed",
                note=(note or "").strip(),
                user_id=user_id,
            )
            session.add(purchase)
            session.flush()

            for line in lines:
                qty = to_float(line.quantity)
                cost = to_float(line.unit_cost)
                if qty <= 0:
                    continue
                session.add(
                    PurchaseItem(
                        purchase_id=purchase.id,
                        product_id=line.product_id,
                        product_name=line.name,
                        quantity=qty,
                        unit_cost=cost,
                        line_total=round(qty * cost, 2),
                    )
                )
                if line.product_id:
                    product = session.get(Product, line.product_id)
                    if product:
                        before = float(product.quantity)
                        after = before + qty
                        product.quantity = after
                        if cost > 0:
                            product.purchase_price = cost
                        session.add(
                            StockMovement(
                                product_id=product.id,
                                movement_type=MOVEMENT_IN,
                                quantity=qty,
                                quantity_before=before,
                                quantity_after=after,
                                unit_cost=cost,
                                reason=f"Achat #{purchase.id}",
                                invoice_number=(invoice_number or "").strip(),
                                supplier_id=supplier_id,
                                user_id=user_id,
                            )
                        )

            credit = round(total - float(purchase.amount_paid), 2)
            purchase_id = purchase.id
            if credit > 0 and supplier_id:
                SupplierDebtService.create_debt(
                    supplier_id,
                    credit,
                    purchase_id=purchase_id,
                    note=f"Crédit achat #{purchase_id}",
                    user_id=user_id,
                    username=username,
                    session=session,
                )

        audit_service.log_action(
            "Création achat",
            "Purchase",
            f"#{purchase_id} total={total} payé={amount_paid} fournisseur={supplier_id}",
            user_id,
            username,
        )
        return cls.get(purchase_id)  # type: ignore[return-value]

    @staticmethod
    def get(purchase_id: int) -> Optional[Purchase]:
        with session_scope() as session:
            purchase = session.scalar(
                select(Purchase)
                .options(
                    joinedload(Purchase.items),
                    joinedload(Purchase.supplier),
                )
                .where(Purchase.id == purchase_id)
            )
            if purchase:
                session.expunge_all()
            return purchase

    @staticmethod
    def list(limit: int = 300) -> List[Purchase]:
        with session_scope() as session:
            rows = session.scalars(
                select(Purchase)
                .options(joinedload(Purchase.supplier))
                .order_by(Purchase.date.desc())
                .limit(limit)
            ).unique().all()
            session.expunge_all()
            return list(rows)
