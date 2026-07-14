"""Génération et impression des tickets thermiques (58 mm / 80 mm).

Deux sorties sont proposées :

- ``render_ticket_text`` construit le ticket en texte monospace (aperçu et
  réimpression, largeur adaptée à 58 ou 80 mm) ;
- ``print_ticket`` envoie le ticket à une imprimante ESC/POS via
  ``python-escpos`` lorsqu'une imprimante est configurée.

Sur un poste sans imprimante (ou en test), on retombe sur un fichier texte
enregistré dans le dossier des tickets, ce qui permet toujours de conserver et
réimprimer une vente.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from app import config
from app.services import settings_service
from app.utils.helpers import format_money, format_quantity

# Nombre de caractères par ligne selon la largeur du papier.
WIDTH_CHARS = {"58mm": 32, "80mm": 48}


def _line(char: str = "-", width: int = 32) -> str:
    return char * width


def _row(left: str, right: str, width: int) -> str:
    """Place ``left`` à gauche et ``right`` à droite sur une même ligne."""
    space = width - len(left) - len(right)
    if space < 1:
        left = left[: max(0, width - len(right) - 1)]
        space = max(1, width - len(left) - len(right))
    return f"{left}{' ' * space}{right}"


def _center(text: str, width: int) -> str:
    return text.center(width)


def render_ticket_text(sale, shop=None, paper: str = "80mm") -> str:
    """Construit le contenu texte d'un ticket à partir d'une vente ORM."""
    shop = shop or settings_service.get_shop_info()
    width = WIDTH_CHARS.get(paper, 48)
    currency = shop.currency or "FCFA"

    lines = []
    lines.append(_center(shop.name or "Commerce", width))
    if shop.address:
        lines.append(_center(shop.address, width))
    if shop.phone:
        lines.append(_center(f"Tel: {shop.phone}", width))
    lines.append(_line("=", width))
    lines.append(_row(f"Ticket: {sale.ticket_number}", "", width))
    moment = sale.date or datetime.now()
    lines.append(_row(f"Date: {moment:%d/%m/%Y}", f"{moment:%H:%M}", width))
    lines.append(_row(f"Caissier: {sale.cashier_name}", "", width))
    if sale.client_id:
        lines.append(_row(f"Client: {sale.client_name}", "", width))
    lines.append(_line("-", width))

    for item in sale.items:
        name = item.product_name
        lines.append(name[:width])
        qty = format_quantity(item.quantity)
        detail = f"{qty} x {format_money(item.unit_price, currency)}"
        lines.append(_row(f"  {detail}", format_money(item.line_total, currency), width))

    lines.append(_line("-", width))
    lines.append(_row("Sous-total", format_money(sale.subtotal, currency), width))
    if float(sale.discount or 0) > 0:
        lines.append(_row("Remise", format_money(sale.discount, currency), width))
    lines.append(_row("TOTAL", format_money(sale.total, currency), width))
    lines.append(_row("Recu", format_money(sale.amount_received, currency), width))
    lines.append(_row("Monnaie", format_money(sale.change_due, currency), width))
    lines.append(_line("-", width))

    if sale.payments:
        lines.append("Paiement:")
        for pay in sale.payments:
            lines.append(_row(f"  {pay.method}", format_money(pay.amount, currency), width))
        lines.append(_line("-", width))

    footer = shop.ticket_footer or "Merci pour votre visite."
    lines.append(_center(footer, width))
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def save_ticket_file(sale, shop=None, paper: str = "80mm") -> Path:
    """Enregistre le ticket dans un fichier texte (repli sans imprimante)."""
    config.ensure_directories()
    content = render_ticket_text(sale, shop, paper)
    path = config.TICKET_DIR / f"{sale.ticket_number}.txt"
    path.write_text(content, encoding="utf-8")
    return path


def print_ticket(
    sale,
    shop=None,
    paper: str = "80mm",
    printer_name: Optional[str] = None,
) -> Path:
    """Imprime le ticket sur une imprimante ESC/POS si possible.

    Retourne toujours le chemin du fichier texte du ticket (généré dans tous les
    cas pour l'archivage et la réimpression). Les erreurs d'impression physique
    ne bloquent pas la vente : le ticket reste disponible en fichier.
    """
    path = save_ticket_file(sale, shop, paper)
    content = render_ticket_text(sale, shop, paper)

    printer_name = printer_name or settings_service.get_setting("printer_name", "")
    if not printer_name:
        return path

    try:  # pragma: no cover - dépend du matériel
        from escpos.printer import File as EscposFile

        device = EscposFile(printer_name)
        device.text(content)
        device.cut()
        device.close()
    except Exception:
        # L'impression physique a échoué : on garde le fichier ticket.
        pass
    return path
