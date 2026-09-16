"""Impression bon serveur / cuisine — Maquis Caisse PC."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Optional

from app.i18n import t
from app.printers import thermal_printer
from app.printers.printer_targets import get_thermal_printer_name
from app.printers.ticket.options import is_kitchen_ticket_enabled
from app.services import settings_service
from app.services.order_service import OrderService


def _sale_stub_from_order(order, cashier_name: str = "") -> SimpleNamespace:
    items = []
    for it in order.items or []:
        items.append(
            SimpleNamespace(
                product_name=it.product_name,
                quantity=float(it.quantity or 0),
                unit_price=float(it.unit_price or 0),
                line_total=float(it.line_total or 0),
            )
        )
    table_label = order.table_label or ""
    if getattr(order, "table", None) is not None:
        table_label = order.table.display_name
    return SimpleNamespace(
        ticket_number=str(order.public_id or ""),
        date=datetime.now(),
        cashier_name=cashier_name,
        client_name=table_label,
        items=items,
        subtotal=float(order.total or 0),
        discount=0.0,
        total=float(order.total or 0),
        amount_received=0.0,
        change_due=0.0,
        payments=[],
    )


def print_kitchen_for_order(
    order_id: int,
    *,
    cashier_name: str = "",
) -> tuple[bool, str]:
    if not is_kitchen_ticket_enabled():
        return False, t(
            "Le bon serveur / cuisine est désactivé dans Paramètres → Designs des tickets."
        )
    order = OrderService.get(order_id)
    if not order or not order.items:
        return False, t("Aucun article à envoyer en cuisine.")
    stub = _sale_stub_from_order(order, cashier_name=cashier_name)
    paper = settings_service.get_setting("thermal_width", "80mm") or "80mm"
    result = thermal_printer.print_ticket(
        stub,
        paper=paper,
        printer_name=get_thermal_printer_name(),
        role="kitchen",
    )
    if result.printed:
        return True, result.message or t("Bon serveur envoyé.")
    return False, result.message or t("Impression impossible.")
