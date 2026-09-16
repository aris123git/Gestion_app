"""Inventaire Maquis PC — parité InventaireScreen (écarts tracés)."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from app.controllers.sale_controller import CartLine
from app.controllers.stock_controller import StockController
from app.models.open_order_payment import OpenOrderPayment
from app.services.order_service import OrderService
from app.database.connection import session_scope


class InventaireEcartReason(str, Enum):
    PERTE = "perte"
    CASSE = "casse"
    AUTRE = "autre"
    ERREUR_SAISIE = "erreur_saisie"
    VENTE_HORS_CAISSE = "vente_hors_caisse"

    @property
    def label(self) -> str:
        return {
            InventaireEcartReason.PERTE: "Perte",
            InventaireEcartReason.CASSE: "Casse",
            InventaireEcartReason.AUTRE: "Autre",
            InventaireEcartReason.ERREUR_SAISIE: "Erreur de saisie",
            InventaireEcartReason.VENTE_HORS_CAISSE: "Vente hors caisse",
        }[self]


def apply_inventory_count(
    product_id: int,
    product_name: str,
    theoretical: float,
    counted: float,
    *,
    reason: Optional[InventaireEcartReason],
    comment: Optional[str],
    user_id: Optional[int],
    unit_price: float,
    purchase_price: float,
) -> str:
    gap = counted - theoretical
    if abs(gap) < 0.0001:
        return f"{product_name} : stock conforme ({counted:g})"

    if gap > 0:
        StockController.stock_in(
            product_id,
            gap,
            reason="Inventaire — surplus",
            user_id=user_id,
            comment=comment or InventaireEcartReason.ERREUR_SAISIE.label,
        )
        return f"{product_name} : écart +{gap:g} enregistré"

    qty = -gap
    if reason == InventaireEcartReason.VENTE_HORS_CAISSE:
        line = CartLine(
            product_id=product_id,
            name=product_name,
            unit_price=float(unit_price),
            quantity=qty,
            purchase_price=float(purchase_price),
        )
        order = OrderService.create_from_cart(
            [line],
            opened_by=user_id,
            mark_paid=True,
        )
        with session_scope() as session:
            session.add(
                OpenOrderPayment(
                    order_id=order.id,
                    payment_mode="Autre",
                    amount=float(order.total or 0),
                    amount_tendered=float(order.total or 0),
                    change_amount=0.0,
                    user_id=user_id,
                    user_name="",
                )
            )
        return f"{product_name} : vente hors caisse ({qty:g}) enregistrée"

    if reason in (
        InventaireEcartReason.PERTE,
        InventaireEcartReason.CASSE,
        InventaireEcartReason.AUTRE,
    ):
        label = reason.label if reason else "Perte"
        StockController.stock_out(
            product_id,
            qty,
            reason=label,
            user_id=user_id,
            comment=comment or "",
        )
        return f"{product_name} : écart {gap:g} enregistré"

    StockController.set_inventory(
        product_id,
        counted,
        reason=(reason.label if reason else "Inventaire"),
        user_id=user_id,
        comment=comment or "",
    )
    return f"{product_name} : écart {gap:g} enregistré"
