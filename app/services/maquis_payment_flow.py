"""Flux UI paiement Maquis → enregistrement commande."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.i18n import t
from app.services import permissions as perms, product_profile
from app.services.maquis_order_service import MaquisOrderService
from app.services.maquis_payment import MODE_CASH
from app.ui.dialogs.maquis_payment_dialog import MaquisPaymentDialog, MaquisPaymentResult
from app.ui.widgets.helpers import info, warn
from app.utils.helpers import format_money

if TYPE_CHECKING:
    from app.ui.state import AppState


def run_maquis_payment(
    total: float,
    parent,
    *,
    allow_partial: bool = False,
    state: Optional["AppState"] = None,
) -> Optional[MaquisPaymentResult]:
    if total <= 0:
        warn(parent, t("Montant total invalide"))
        return None
    allow_credit = True
    if state is not None:
        allow_credit = state.can(perms.SELL_ON_CREDIT)
    dlg = MaquisPaymentDialog(
        total,
        parent,
        allow_partial=allow_partial,
        allow_credit=allow_credit,
    )
    if not dlg.exec() or not dlg.result_data:
        return None
    return dlg.result_data


def apply_payment_to_order(
    order_id: int,
    pay: MaquisPaymentResult,
    *,
    user_id: Optional[int],
    user_name: str,
    remaining_before: float,
) -> None:
    if pay.partial_with_debt_remainder:
        br = pay.breakdown
        MaquisOrderService.pay_partial_with_debt_remainder(
            order_id,
            br.mode,
            br.total_amount,
            br.amount_tendered or br.total_amount,
            debt_customer_name="",
            user_id=user_id,
            user_name=user_name,
            debt_client_id=pay.debt_client_id,
        )
        return
    MaquisOrderService.pay_order(
        order_id,
        pay.breakdown,
        user_id=user_id,
        user_name=user_name,
        debt_client_id=pay.debt_client_id,
    )


def checkout_order_maquis(
    order_id: int,
    remaining: float,
    state: "AppState",
    parent,
) -> bool:
    from app.services.order_service import OrderService

    pay = run_maquis_payment(remaining, parent, allow_partial=True, state=state)
    if not pay:
        return False
    user = getattr(state.current_user, "username", "") or ""
    try:
        apply_payment_to_order(
            order_id,
            pay,
            user_id=state.user_id,
            user_name=user,
            remaining_before=remaining,
        )
    except ValueError as exc:
        warn(parent, str(exc))
        return False
    order = OrderService.get(order_id)
    from app.services import settings_service

    currency = settings_service.get_currency()
    msg = t("Paiement enregistré.")
    if order and float(order.remaining_amount) > 0.009:
        msg = t("Paiement partiel enregistré.")
    info(
        parent,
        f"{msg}\n{t('Monnaie rendue')} : {format_money(pay.change_amount, currency)}",
        t("Encaissement"),
    )
    state.notify_data_changed()
    return True


def checkout_cart_maquis(
    order_id: int,
    total: float,
    state: "AppState",
    parent,
) -> bool:
    """Après création commande depuis panier — encaissement total."""
    if not product_profile.is_maquis():
        return False
    pay = run_maquis_payment(total, parent, allow_partial=False, state=state)
    if not pay:
        return False
    user = getattr(state.current_user, "username", "") or ""
    try:
        apply_payment_to_order(
            order_id,
            pay,
            user_id=state.user_id,
            user_name=user,
            remaining_before=total,
        )
    except ValueError as exc:
        warn(parent, str(exc))
        return False
    return True
