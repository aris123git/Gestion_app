"""Encaissement commande Maquis — parité mobile, sans ticket client."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.i18n import t
from app.models.open_order import STATUS_OPEN, STATUS_UNPAID
from app.services import product_profile
from app.services.maquis_payment_flow import checkout_order_maquis
from app.services.order_service import OrderService
from app.ui.widgets.helpers import warn

if TYPE_CHECKING:
    from app.ui.state import AppState


def checkout_open_order(
    order_id: int,
    state: "AppState",
    parent,
    *,
    confirm_payment: bool = True,
) -> bool:
    order = OrderService.get(order_id)
    if not order or order.status not in (STATUS_OPEN, STATUS_UNPAID):
        warn(parent, t("Commande introuvable ou déjà clôturée."))
        return False
    if not order.items:
        warn(parent, t("La commande ne contient aucun article."))
        return False
    if product_profile.is_maquis():
        remaining = float(order.remaining_amount)
        return checkout_order_maquis(order_id, remaining, state, parent)

    from app.controllers.sale_controller import (
        BelowMinPriceError,
        CartLine,
        InsufficientPaymentError,
        InsufficientStockError,
        SaleController,
    )
    from app.services import permissions as perms, settings_service
    from app.ui.dialogs.payment_dialog import PaymentDialog
    from app.ui.widgets.helpers import info
    from app.utils.helpers import format_money
    from app import config
    from typing import Optional

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

    lines = order_to_cart_lines(order)
    prior_paid = float(order.paid_amount or 0)
    total_due = float(order.remaining_amount)
    dialog = PaymentDialog(
        total_due,
        client_id=None,
        client_phone="",
        allow_credit=state.can(perms.SELL_ON_CREDIT),
        max_credit=_cashier_max_credit(state),
        parent=parent,
    )
    if confirm_payment and not dialog.exec():
        return False
    credit_requested = dialog.use_credit or any(
        p.method == config.PAYMENT_METHOD_CREDIT for p in dialog.result_payments
    )
    if credit_requested and (not state.can(perms.SELL_ON_CREDIT)):
        warn(parent, t("Vous n'avez pas l'autorisation de vendre à crédit."))
        return False
    try:
        result = SaleController.create_sale(
            lines=lines,
            payments=dialog.result_payments,
            amount_received=dialog.amount_received,
            discount=prior_paid,
            client_id=dialog.result_client_id,
            user_id=state.user_id,
            allow_credit=credit_requested,
            debt_due_date=dialog.credit_due_date,
            loyalty_credit=0,
        )
    except (InsufficientPaymentError, InsufficientStockError, BelowMinPriceError, ValueError) as exc:
        warn(parent, str(exc))
        return False
    user = getattr(state.current_user, "username", "") or ""
    OrderService.attach_sale_payment(
        order_id,
        result.sale_id,
        dialog.result_payments,
        user_id=state.user_id,
        user_name=user,
    )
    currency = settings_service.get_currency()
    info(
        parent,
        f"{t('Commande')} {order.public_id} {t('clôturée')}.\n"
        f"{t('Monnaie rendue')} : {format_money(dialog.change_due, currency)}",
        t("Encaissement"),
    )
    state.notify_data_changed()
    return True


def _cashier_max_credit(state: "AppState"):
    from typing import Optional
    from app.services.cash_controls import limits_for_user

    _, max_credit = limits_for_user(state.current_user)
    return max_credit
