"""Flux commande Maquis PC — parité app mobile (stock, paiements, dettes)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select

from app import config
from app.database.connection import session_scope
from app.models.dining_table import STATUS_CLEANING, STATUS_FREE, STATUS_OCCUPIED
from app.models.open_order import (
    STATUS_CANCELLED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_SERVED,
    STATUS_UNPAID,
    OpenOrder,
)
from app.models.open_order_payment import OpenOrderPayment
from app.models.product import Product
from app.models.stock import MOVEMENT_CORRECTION, MOVEMENT_SALE, StockMovement
from app.services import product_profile
from app.services.debt_service import DebtService
from app.services.maquis_payment import (
    MODE_CASH,
    PaymentBreakdown,
    breakdown_to_payment_lines,
    simple_pay,
)


def _maquis_active() -> bool:
    return product_profile.is_maquis()


def _apply_stock_delta(
    session,
    product_id: int,
    delta_qty: float,
    *,
    movement_type: str,
    reason: str,
    user_id: Optional[int],
) -> None:
    product = session.get(Product, product_id)
    if not product or not product_id:
        return
    before = float(product.quantity or 0)
    after = before + delta_qty
    if delta_qty < 0 and after < -0.0001:
        raise ValueError(f"Stock insuffisant : « {product.name} »")
    product.quantity = after
    session.add(
        StockMovement(
            product_id=product.id,
            movement_type=movement_type,
            quantity=abs(delta_qty),
            quantity_before=before,
            quantity_after=after,
            reason=reason,
            user_id=user_id,
        )
    )


def consume_lines_stock(
    lines,
    *,
    public_id: str,
    user_id: Optional[int],
    session,
) -> None:
    if not _maquis_active():
        return
    for line in lines:
        pid = getattr(line, "product_id", None) or (
            line.get("product_id") if isinstance(line, dict) else None
        )
        if not pid:
            continue
        qty = float(
            getattr(line, "quantity", None)
            or (line.get("quantity") if isinstance(line, dict) else 0)
            or 0
        )
        if qty <= 0:
            continue
        _apply_stock_delta(
            session,
            int(pid),
            -qty,
            movement_type=MOVEMENT_SALE,
            reason=f"Commande {public_id}",
            user_id=user_id,
        )


def restore_order_stock(order: OpenOrder, *, user_id: Optional[int], session) -> None:
    if not _maquis_active():
        return
    for item in order.items or []:
        if not item.product_id:
            continue
        qty = float(item.quantity or 0)
        if qty <= 0:
            continue
        _apply_stock_delta(
            session,
            int(item.product_id),
            qty,
            movement_type=MOVEMENT_CORRECTION,
            reason=f"Annulation {order.public_id}",
            user_id=user_id,
        )


def _set_table_after_pay(session, order: OpenOrder) -> None:
    from app.models.dining_table import DiningTable

    if not order.table_id:
        return
    table = session.get(DiningTable, order.table_id)
    if not table:
        return
    if order.status == STATUS_PAID:
        table.status = STATUS_CLEANING
    elif order.status in (STATUS_OPEN, STATUS_SERVED, STATUS_UNPAID):
        table.status = STATUS_OCCUPIED


class MaquisOrderService:
    @staticmethod
    def pay_order(
        order_id: int,
        breakdown: PaymentBreakdown,
        *,
        user_id: Optional[int] = None,
        user_name: str = "",
        debt_client_id: Optional[int] = None,
        debt_customer_name: str = "",
    ) -> OpenOrder:
        payments = breakdown_to_payment_lines(breakdown)
        return MaquisOrderService.pay_order_lines(
            order_id,
            payments,
            user_id=user_id,
            user_name=user_name,
            debt_client_id=debt_client_id,
            debt_customer_name=debt_customer_name,
            change_amount=breakdown.change_amount,
        )

    @staticmethod
    def pay_order_lines(
        order_id: int,
        payments: list,
        *,
        user_id: Optional[int] = None,
        user_name: str = "",
        debt_client_id: Optional[int] = None,
        debt_customer_name: str = "",
        change_amount: float = 0.0,
    ) -> OpenOrder:
        with session_scope() as session:
            order = session.get(OpenOrder, order_id)
            if not order or order.status not in (STATUS_OPEN, STATUS_SERVED, STATUS_UNPAID):
                raise ValueError("Commande non payable")
            paid_delta = 0.0
            debt_total = 0.0
            for pay in payments or []:
                amt = round(float(getattr(pay, "amount", 0) or 0), 2)
                if amt <= 0:
                    continue
                paid_delta += amt
                method = str(getattr(pay, "method", MODE_CASH) or MODE_CASH)
                if method in (config.PAYMENT_METHOD_CREDIT, "Dette", "DEBT"):
                    debt_total += amt
                session.add(
                    OpenOrderPayment(
                        order_id=order.id,
                        payment_mode=method,
                        amount=amt,
                        amount_tendered=float(
                            getattr(pay, "amount_tendered", amt) or amt
                        ),
                        change_amount=change_amount if method == MODE_CASH else 0.0,
                        user_id=user_id,
                        user_name=user_name or "",
                    )
                )
            order.paid_amount = round(float(order.paid_amount or 0) + paid_delta, 2)
            total = float(order.total or 0)
            if order.paid_amount + 0.009 >= total:
                order.paid_amount = total
                order.status = STATUS_PAID
                order.closed_at = datetime.utcnow()
            else:
                order.status = STATUS_UNPAID
            _set_table_after_pay(session, order)
            session.flush()
            if debt_total > 0 and debt_client_id:
                DebtService.create_debt(
                    debt_client_id,
                    debt_total,
                    sale_id=order.sale_id,
                    note=f"Commande {order.public_id}",
                    user_id=user_id,
                    username=user_name,
                    session=session,
                )
            session.refresh(order)
            session.expunge(order)
            return order

    @staticmethod
    def pay_partial_with_debt_remainder(
        order_id: int,
        paid_mode: str,
        paid_amount: float,
        amount_tendered: float,
        *,
        debt_customer_name: str = "",
        user_id: Optional[int] = None,
        user_name: str = "",
        debt_client_id: Optional[int] = None,
    ) -> OpenOrder:
        from app.services.order_service import OrderService

        order = OrderService.get(order_id)
        if not order:
            raise ValueError("Commande introuvable")
        remaining = float(order.remaining_amount)
        pay_amount = min(round(float(paid_amount), 2), remaining)
        br = simple_pay(remaining, paid_mode, pay_amount, amount_tendered)
        order = MaquisOrderService.pay_order(
            order_id,
            br,
            user_id=user_id,
            user_name=user_name,
            debt_client_id=debt_client_id,
            debt_customer_name=debt_customer_name,
        )
        order = OrderService.get(order_id)
        if not order:
            return order
        rest = float(order.remaining_amount)
        if rest <= 0.009:
            return order
        debt_br = simple_pay(rest, config.PAYMENT_METHOD_CREDIT, rest, 0)
        return MaquisOrderService.pay_order(
            order_id,
            debt_br,
            user_id=user_id,
            user_name=user_name,
            debt_client_id=debt_client_id,
            debt_customer_name=debt_customer_name,
        )
