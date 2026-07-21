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

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from app import config
from app.services import settings_service
from app.utils.helpers import format_money, format_quantity


@dataclass
class PrintResult:
    """Résultat d'une tentative d'impression.

    - ``printed`` : True si les données ont bien été envoyées à une imprimante ;
    - ``file_path`` : chemin de la copie texte du ticket (toujours créée) ;
    - ``message`` : explication (utile en cas d'échec ou d'absence d'imprimante).
    """

    printed: bool
    file_path: Path
    message: str = ""

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


def _build_escpos_bytes(content: str) -> bytes:
    """Génère le flux ESC/POS (texte + coupe) sans matériel, via un tampon."""
    try:
        from escpos.printer import Dummy

        dummy = Dummy()
        dummy.text(content + "\n")
        try:
            dummy.cut()
        except Exception:
            # Certaines configurations n'autorisent pas la commande de coupe.
            pass
        return dummy.output
    except Exception:
        # Repli : envoi du texte brut si python-escpos est indisponible.
        return (content + "\n").encode("utf-8", errors="replace")


def _print_windows(raw: bytes, printer_name: str) -> PrintResult:  # pragma: no cover
    """Envoie les octets bruts à une imprimante Windows (nom ou par défaut)."""
    try:
        import win32print
    except Exception as exc:
        return PrintResult(False, Path(), f"Module d'impression Windows absent : {exc}")

    target = printer_name or win32print.GetDefaultPrinter()
    if not target:
        return PrintResult(False, Path(), "Aucune imprimante Windows configurée.")
    try:
        handle = win32print.OpenPrinter(target)
        try:
            win32print.StartDocPrinter(handle, 1, ("Ticket", None, "RAW"))
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, raw)
            win32print.EndPagePrinter(handle)
            win32print.EndDocPrinter(handle)
        finally:
            win32print.ClosePrinter(handle)
    except Exception as exc:
        return PrintResult(False, Path(), f"Échec de l'impression Windows : {exc}")
    return PrintResult(True, Path(), f"Imprimé sur « {target} ».")


def _print_posix(raw: bytes, printer_name: str) -> PrintResult:
    """Impression sous Linux/macOS : périphérique brut ou CUPS (lp)."""
    # 1) Chemin de périphérique explicite (ex. /dev/usb/lp0).
    if printer_name and ("/" in printer_name or printer_name.startswith("\\")):
        try:
            with open(printer_name, "wb") as device:
                device.write(raw)
            return PrintResult(True, Path(), f"Imprimé sur « {printer_name} ».")
        except OSError as exc:
            return PrintResult(False, Path(), f"Accès imprimante impossible : {exc}")

    # 2) Sinon, on tente CUPS via la commande « lp » (impression brute).
    command = ["lp", "-o", "raw"]
    if printer_name:
        command += ["-d", printer_name]
    try:
        proc = subprocess.run(
            command, input=raw, capture_output=True, timeout=20, check=False
        )
    except FileNotFoundError:
        return PrintResult(
            False, Path(), "Aucune imprimante configurée (CUPS/lp introuvable)."
        )
    except Exception as exc:  # pragma: no cover - dépend du système
        return PrintResult(False, Path(), f"Échec de l'impression : {exc}")
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or "erreur inconnue"
        return PrintResult(False, Path(), f"Échec de l'impression : {detail}")
    where = printer_name or "imprimante par défaut"
    return PrintResult(True, Path(), f"Imprimé sur « {where} ».")


def print_ticket(
    sale,
    shop=None,
    paper: str = "80mm",
    printer_name: Optional[str] = None,
) -> PrintResult:
    """Imprime réellement le ticket et retourne le résultat de l'opération.

    - Une copie texte du ticket est **toujours** enregistrée (archivage).
    - L'envoi à l'imprimante est effectué selon la plateforme :
      Windows (``win32print`` par nom / imprimante par défaut) ou
      Linux/macOS (périphérique brut ou CUPS ``lp``).
    - Le résultat (``PrintResult``) indique clairement si l'impression a réussi,
      afin que l'interface affiche un message honnête.
    """
    path = save_ticket_file(sale, shop, paper)
    content = render_ticket_text(sale, shop, paper)
    printer_name = (
        printer_name
        if printer_name is not None
        else settings_service.get_setting("printer_name", "")
    ).strip()

    raw = _build_escpos_bytes(content)

    if sys.platform.startswith("win"):
        result = _print_windows(raw, printer_name)
    else:
        result = _print_posix(raw, printer_name)

    result.file_path = path
    if not result.printed and not result.message:
        result.message = "Aucune imprimante configurée."
    return result
