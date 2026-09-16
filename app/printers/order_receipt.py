"""Addition et bon cuisine d'une commande de table (Maquis Caisse).

Une commande ouverte n'est pas encore une vente : on l'expose sous une forme
« vente-like » pour réutiliser les designs de tickets existants (client et
serveur / cuisine). Rien n'est imprimé automatiquement : ces fonctions sont
appelées seulement quand l'utilisateur demande l'addition ou le bon.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Optional

from app.printers import thermal_printer
from app.printers.printer_targets import get_default_paper, printer_for_paper
from app.services import settings_service


def _thermal_paper(paper: Optional[str] = None) -> str:
    """Format thermique utilisable (l'addition d'un maquis n'est pas une facture A4)."""
    candidate = paper or get_default_paper()
    if candidate not in ("58mm", "80mm"):
        candidate = settings_service.get_setting("ticket_format", "80mm")
    if candidate not in ("58mm", "80mm"):
        candidate = "80mm"
    return candidate


def order_as_sale(order, *, cashier: str = "") -> SimpleNamespace:
    """Vue « vente » d'une commande ouverte, pour l'aperçu et l'impression."""
    table_name = ""
    table = getattr(order, "table", None)
    if table is not None:
        table_name = table.display_name
    items = [
        SimpleNamespace(
            product_name=(
                f"{item.product_name} ({item.note})"
                if str(getattr(item, "note", "") or "").strip()
                else item.product_name
            ),
            quantity=float(item.quantity or 0),
            unit_price=float(item.unit_price or 0),
            line_total=float(item.line_total or 0),
            product_id=item.product_id,
        )
        for item in (order.items or [])
    ]
    total = round(sum(item.line_total for item in items), 2)
    client_name = (order.customer_name or "").strip()
    if table_name:
        client_name = f"{table_name} — {client_name}" if client_name else table_name
    return SimpleNamespace(
        ticket_number=order.public_id or f"CMD-{order.id}",
        date=getattr(order, "created_at", None) or datetime.now(),
        cashier_name=cashier,
        client_id=None,
        client_name=client_name,
        items=items,
        subtotal=total,
        discount=0.0,
        total=total,
        amount_received=0.0,
        change_due=0.0,
        payments=[],
    )


def render_order_bill_text(order, *, paper: Optional[str] = None, cashier: str = "") -> str:
    """Aperçu texte de l'addition (pas encore encaissée)."""
    return thermal_printer.render_ticket_text(
        order_as_sale(order, cashier=cashier), paper=_thermal_paper(paper)
    )


def print_order_bill(
    order,
    *,
    paper: Optional[str] = None,
    printer_name: Optional[str] = None,
    cashier: str = "",
) -> thermal_printer.PrintResult:
    """Imprime l'addition à la demande (jamais automatiquement)."""
    resolved = _thermal_paper(paper)
    target = printer_name if printer_name is not None else printer_for_paper(resolved)
    return thermal_printer.print_ticket(
        order_as_sale(order, cashier=cashier),
        paper=resolved,
        printer_name=target,
        role="client",
    )


def print_order_kitchen(
    order,
    *,
    paper: Optional[str] = None,
    printer_name: Optional[str] = None,
    cashier: str = "",
) -> thermal_printer.PrintResult:
    """Imprime le bon cuisine / serveur (sans prix) à la demande."""
    resolved = _thermal_paper(paper)
    target = printer_name if printer_name is not None else printer_for_paper(resolved)
    return thermal_printer.print_ticket(
        order_as_sale(order, cashier=cashier),
        paper=resolved,
        printer_name=target,
        role="kitchen",
    )
