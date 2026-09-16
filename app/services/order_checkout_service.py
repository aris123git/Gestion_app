"""Encaissement commande table Maquis — vente en base, sans impression ticket."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app import config
from app.controllers.sale_controller import (
    BelowMinPriceError,
    CartLine,
    InsufficientPaymentError,
    InsufficientStockError,
    SaleController,
)
from app.i18n import t
from app.models.open_order import STATUS_OPEN
from app.services import permissions as perms, settings_service
from app.services.order_service import OrderService
from app.ui.dialogs.payment_dialog import PaymentDialog
from app.ui.widgets.helpers import info, warn

if TYPE_CHECKING:
    from app.ui.state import AppState


def order_to_cart_lines(order) -> list[CartLine]:
    lines: list[CartLine] = []
    for it in order.items or []:
        lines.append(
            CartLine(
                product_id=it.product_id,
                name=str(it.product_name or ""),
                unit_price=float(it.unit_price or 0),
                quantity=float(it.quantity or 0),
                purchase_price=0.0,
            )
        )
    return lines


def checkout_open_order(
    order_id: int,
    state: "AppState",
    parent,
    *,
    confirm_payment: bool = True,
) -> bool:
    """Encaisse la commande (PaymentDialog), crée la vente, marque payée — pas de ticket."""
    order = OrderService.get(order_id)
    if not order or order.status != STATUS_OPEN:
        warn(parent, t("Commande introuvable ou déjà clôturée."))
        return False
    if not order.items:
        warn(parent, t("La commande ne contient aucun article."))
        return False
    lines = order_to_cart_lines(order)
    total = float(order.total or 0)
    dialog = PaymentDialog(
        total,
        client_id=None,
        client_phone="",
        allow_credit=state.can(perms.SELL_ON_CREDIT),
        max_credit=_cashier_max_credit(state),
        parent=parent,
    )
    if confirm_payment and not dialog.exec():
        return False
    try:
        credit_requested = dialog.use_credit or any(
            p.method == config.PAYMENT_METHOD_CREDIT for p in dialog.result_payments
        )
        if credit_requested and (not state.can(perms.SELL_ON_CREDIT)):
            warn(parent, t("Vous n'avez pas l'autorisation de vendre à crédit."))
            return False
        result = SaleController.create_sale(
            lines=lines,
            payments=dialog.result_payments,
            amount_received=dialog.amount_received,
            discount=0.0,
            client_id=dialog.result_client_id,
            user_id=state.user_id,
            allow_credit=credit_requested,
            debt_due_date=dialog.credit_due_date,
            loyalty_credit=0,
        )
    except InsufficientPaymentError as exc:
        warn(parent, str(exc), t("Paiement insuffisant"))
        return False
    except InsufficientStockError as exc:
        warn(parent, str(exc), t("Stock insuffisant"))
        return False
    except BelowMinPriceError as exc:
        warn(parent, str(exc), t("Prix minimum"))
        return False
    except ValueError as exc:
        warn(parent, str(exc))
        return False
    OrderService.mark_paid(order_id)
    currency = settings_service.get_currency()
    from app.utils.helpers import format_money

    info(
        parent,
        f"Vente enregistrée : {result.ticket_number}\n"
        f"Total : {format_money(result.total, currency)}\n"
        f"Commande {order.public_id} clôturée (sans impression ticket).",
        t("Encaissement"),
    )
    state.notify_data_changed()
    return True


def _cashier_max_credit(state: "AppState") -> Optional[float]:
    from app.services.cash_controls import limits_for_user

    _, max_credit = limits_for_user(state.current_user)
    return max_credit
