"""Génération et impression des tickets thermiques (58 mm / 80 mm)
et factures demi-A4 (papier A4 coupé en deux).

Deux sorties sont proposées :

- ``render_ticket_text`` construit le ticket en texte monospace (aperçu et
  réimpression, largeur adaptée au format) ;
- ``print_ticket`` envoie le ticket à une imprimante ESC/POS (thermique)
  ou génère/imprime un PDF demi-A4 pour imprimante bureau.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from app import config
from app.services import settings_service
from app.utils.helpers import format_money, format_quantity

logger = logging.getLogger(__name__)


@dataclass
class PrintResult:
    """Résultat d'une tentative d'impression.

    - ``printed`` : True si les données ont bien été envoyées à une imprimante ;
    - ``file_path`` : chemin de la copie texte/PDF du ticket (toujours créée) ;
    - ``message`` : explication (utile en cas d'échec ou d'absence d'imprimante).
    """

    printed: bool
    file_path: Path
    message: str = ""

# Nombre de caractères par ligne selon la largeur du papier.
WIDTH_CHARS = {"58mm": 32, "80mm": 48, "demi-A4": 72}
PAPER_FORMATS = ("80mm", "58mm", "demi-A4")

# Présentations thermique (paramètre ``ticket_layout``).
TICKET_LAYOUT_CLASSIC = "classic"
TICKET_LAYOUT_COMPACT = "compact"
TICKET_LAYOUT_TABLE = "table"
TICKET_LAYOUT_KITCHEN = "kitchen"
TICKET_LAYOUTS = (
    TICKET_LAYOUT_CLASSIC,
    TICKET_LAYOUT_COMPACT,
    TICKET_LAYOUT_TABLE,
    TICKET_LAYOUT_KITCHEN,
)
TICKET_LAYOUT_LABELS = {
    TICKET_LAYOUT_CLASSIC: "Classique (nom + détail)",
    TICKET_LAYOUT_COMPACT: "Compact (une ligne)",
    TICKET_LAYOUT_TABLE: "Tableau (Qté / Prix / Total)",
    TICKET_LAYOUT_KITCHEN: "Bon serveur — court (quoi servir)",
}


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


def _resolve_layout(layout: Optional[str]) -> str:
    if layout in TICKET_LAYOUTS:
        return layout
    stored = settings_service.get_setting("ticket_layout", TICKET_LAYOUT_CLASSIC)
    return stored if stored in TICKET_LAYOUTS else TICKET_LAYOUT_CLASSIC


def _item_amounts(item) -> tuple[str, float, float]:
    qty = format_quantity(item.quantity)
    unit_price = float(item.unit_price or 0)
    line_total = float(item.line_total or 0)
    return qty, unit_price, line_total


def _render_items_classic(items, width: int, currency: str) -> list[str]:
    lines: list[str] = []
    for item in items:
        name = item.product_name or ""
        lines.append(name[:width])
        qty, unit_price, line_total = _item_amounts(item)
        expected = round(unit_price * float(item.quantity or 0), 2)
        if abs(expected - line_total) > 0.01:
            detail = f"montant {format_money(line_total, currency)}"
        else:
            detail = f"{qty} x {format_money(unit_price, currency)}"
        lines.append(_row(f"  {detail}", format_money(line_total, currency), width))
    return lines


def _render_items_compact(items, width: int, currency: str) -> list[str]:
    lines: list[str] = []
    for item in items:
        name = (item.product_name or "").strip()
        qty, unit_price, line_total = _item_amounts(item)
        total_txt = format_money(line_total, currency)
        # Ex. "2x Jus ........ 1 000"
        left = f"{qty}x {name}"
        max_left = max(8, width - len(total_txt) - 1)
        if len(left) > max_left:
            lines.append(name[:width])
            lines.append(_row(f"  {qty}x", total_txt, width))
        else:
            lines.append(_row(left, total_txt, width))
    return lines


def _render_items_table(items, width: int, currency: str) -> list[str]:
    """Tableau Qté / Prix / Total (adapté 58 et 80 mm)."""
    lines: list[str] = []
    if width <= 32:
        # 58 mm : colonnes serrées.
        header = f"{'Qté':>4} {'Prix':>10} {'Total':>12}"
        lines.append(header[:width].ljust(width) if len(header) <= width else header[:width])
        lines.append(_line("-", width))
        for item in items:
            name = (item.product_name or "")[:width]
            lines.append(name)
            qty, unit_price, line_total = _item_amounts(item)
            row = (
                f"{qty:>4} "
                f"{format_money(unit_price, currency):>10} "
                f"{format_money(line_total, currency):>12}"
            )
            lines.append(row[:width])
    else:
        # 80 mm : en-tête plus lisible.
        lines.append(_row("Article", "Qté  Prix     Total", width))
        lines.append(_line("-", width))
        for item in items:
            name = (item.product_name or "")[: max(12, width - 22)]
            qty, unit_price, line_total = _item_amounts(item)
            right = (
                f"{qty:>4} "
                f"{format_money(unit_price, currency):>8} "
                f"{format_money(line_total, currency):>9}"
            )
            lines.append(_row(name, right, width))
    return lines


def _render_items_kitchen(items, width: int, currency: str) -> list[str]:
    """Produits mis en exergue, sans gaspiller de papier.

    Une seule ligne par article : ``2x CAFE EXPRESS``.
    Le client présente le ticket ; le serveur lit d'un coup d'œil.
    """
    lines: list[str] = []
    item_list = list(items)
    for item in item_list:
        qty, _unit, _total = _item_amounts(item)
        name = (item.product_name or "").strip().upper()
        left = f"{qty}x {name}"
        if len(left) <= width:
            lines.append(left)
        else:
            # Nom long : qté sur la 1re ligne, suite du nom sur la suivante.
            lines.append(f"{qty}x {name[: max(0, width - len(qty) - 2)]}")
            rest = name[max(0, width - len(qty) - 2) :]
            while rest:
                lines.append(rest[:width])
                rest = rest[width:]
    _ = currency
    return lines


def render_ticket_text(
    sale,
    shop=None,
    paper: str = "80mm",
    layout: Optional[str] = None,
) -> str:
    """Construit le contenu texte d'un ticket à partir d'une vente ORM."""
    from app.printers.half_a4_invoice import HALF_A4_WIDTH_CHARS, is_half_a4

    shop = shop or settings_service.get_shop_info()
    if is_half_a4(paper):
        width = HALF_A4_WIDTH_CHARS
    else:
        width = WIDTH_CHARS.get(paper, 48)
    currency = shop.currency or "FCFA"
    layout_id = _resolve_layout(layout)
    # Demi-A4 garde le rendu classique (PDF a son propre moteur).
    if is_half_a4(paper):
        layout_id = TICKET_LAYOUT_CLASSIC

    lines = []
    logo_path = Path(str(shop.logo_path or ""))
    shop_name = shop.name or "Commerce"
    if layout_id == TICKET_LAYOUT_KITCHEN:
        # En-tête court : pas de logo / adresse / footer = économise le papier.
        lines.append(_center("A SERVIR", width))
        lines.append(
            _row(
                f"{sale.ticket_number}",
                f"{(sale.date or datetime.now()):%H:%M}",
                width,
            )
        )
        lines.append(_line("-", width))
        lines.extend(_render_items_kitchen(sale.items, width, currency))
        lines.append(_line("-", width))
        return "\n".join(lines)

    if is_half_a4(paper):
        lines.append(_center("FACTURE", width))
    if shop.logo_path and logo_path.exists():
        lines.append(_center(shop_name.upper(), width))
    else:
        lines.append(_center(shop_name, width))
    if shop.address:
        lines.append(_center(shop.address, width))
    if shop.phone:
        lines.append(_center(f"Tel: {shop.phone}", width))
    lines.append(_line("=", width))
    label = "Facture" if is_half_a4(paper) else "Ticket"
    lines.append(_row(f"{label}: {sale.ticket_number}", "", width))
    moment = sale.date or datetime.now()
    lines.append(_row(f"Date: {moment:%d/%m/%Y}", f"{moment:%H:%M}", width))
    lines.append(_row(f"Caissier: {sale.cashier_name}", "", width))
    if sale.client_id:
        lines.append(_row(f"Client: {sale.client_name}", "", width))
    lines.append(_line("-", width))

    items = list(sale.items or [])
    if layout_id == TICKET_LAYOUT_COMPACT:
        lines.extend(_render_items_compact(items, width, currency))
    elif layout_id == TICKET_LAYOUT_TABLE:
        lines.extend(_render_items_table(items, width, currency))
    else:
        lines.extend(_render_items_classic(items, width, currency))

    lines.append(_line("-", width))
    lines.append(_row("Sous-total", format_money(sale.subtotal, currency), width))
    if float(sale.discount or 0) > 0:
        lines.append(_row("Remise", format_money(sale.discount, currency), width))
    vat_rate = settings_service.get_vat_rate()
    if vat_rate > 0:
        total_ttc = float(sale.total or 0)
        vat_amount = round(total_ttc * vat_rate / (100 + vat_rate), 2)
        total_ht = round(total_ttc - vat_amount, 2)
        lines.append(_row("TOTAL TTC", format_money(total_ttc, currency), width))
        lines.append(_row("Total HT", format_money(total_ht, currency), width))
        lines.append(
            _row(f"dont TVA {vat_rate:g}%", format_money(vat_amount, currency), width)
        )
    else:
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
    if is_half_a4(paper):
        lines.append(_center("Format demi-A4 (210 × 148,5 mm)", width))
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def save_ticket_file(sale, shop=None, paper: str = "80mm") -> Path:
    """Enregistre le ticket dans un fichier texte (repli sans imprimante)."""
    config.ensure_directories()
    content = render_ticket_text(sale, shop, paper)
    path = config.TICKET_DIR / f"{sale.ticket_number}.txt"
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.TICKET_DIR / f"{sale.ticket_number}_{stamp}.txt"
        counter = 1
        while path.exists():
            path = config.TICKET_DIR / f"{sale.ticket_number}_{stamp}_{counter}.txt"
            counter += 1
    path.write_text(content, encoding="utf-8")
    return path


# Nombre de lignes d'avance papier par défaut avant la coupe. Nécessaire pour
# que la fin du ticket dépasse la tête d'impression et le massicot.
DEFAULT_FEED_LINES = 5
# Mode de coupe par défaut : "full" (complète), "partial" (partielle) ou "none".
DEFAULT_CUT_MODE = "full"

_CUT_MODES = {"full": "FULL", "partial": "PART"}


def list_printers() -> list[str]:
    """Retourne la liste des imprimantes installées sur le poste.

    - Windows : via ``win32print`` (imprimantes locales et partagées) ;
    - Linux/macOS : via ``lpstat`` (CUPS).
    En cas d'échec ou d'absence d'outil, retourne une liste vide.
    """
    if sys.platform.startswith("win"):  # pragma: no cover - dépend de Windows
        try:
            import win32print

            flags = (
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            )
            return [printer[2] for printer in win32print.EnumPrinters(flags)]
        except Exception:
            return []
    try:
        proc = subprocess.run(
            ["lpstat", "-a"], capture_output=True, timeout=5, text=True, check=False
        )
        return [
            line.split()[0]
            for line in proc.stdout.splitlines()
            if line.strip()
        ]
    except Exception:
        return []


def default_printer() -> str:
    """Retourne le nom de l'imprimante par défaut du système."""
    if sys.platform.startswith("win"):  # pragma: no cover - dépend de Windows
        try:
            import win32print

            return win32print.GetDefaultPrinter() or ""
        except Exception:
            return ""
    try:
        proc = subprocess.run(
            ["lpstat", "-d"], capture_output=True, timeout=5, text=True, check=False
        )
        if proc.returncode != 0:
            return ""
        # Exemple CUPS : "system default destination: Epson_TM_T20"
        marker = ":"
        line = proc.stdout.strip()
        if marker in line:
            return line.split(marker, 1)[1].strip()
    except Exception:
        return ""
    return ""


# Largeur d'impression (points) selon le papier, pour redimensionner le logo.
_LOGO_WIDTH_DOTS = {"58mm": 384, "80mm": 576}


def _load_logo_image(logo_path: Optional[str], paper: str):
    """Charge et redimionne le logo pour l'impression (retourne une image PIL)."""
    if not logo_path:
        return None
    path = Path(str(logo_path))
    if not path.exists():
        return None
    try:
        from PIL import Image

        image = Image.open(path).convert("L")  # niveaux de gris
        max_width = _LOGO_WIDTH_DOTS.get(paper, 576)
        if image.width > max_width:
            ratio = max_width / float(image.width)
            image = image.resize((max_width, max(1, int(image.height * ratio))))
        return image
    except Exception:
        logger.debug("Impossible de charger le logo du ticket thermique.", exc_info=True)
        return None


def _build_escpos_serveur_bytes(
    sale,
    shop=None,
    *,
    feed_lines: int = DEFAULT_FEED_LINES,
    cut_mode: str = DEFAULT_CUT_MODE,
    logo_path: Optional[str] = None,
    paper: str = "80mm",
) -> bytes:
    """ESC/POS compact : produits en gras (sans double hauteur = pas de surconsommation)."""
    shop = shop or settings_service.get_shop_info()
    feed_lines = max(0, int(feed_lines))
    # Pas de logo sur le bon serveur (trop de papier).
    _ = logo_path
    _ = shop
    try:
        from escpos.printer import Dummy

        dummy = Dummy()
        dummy.set(align="center", bold=True, width=1, height=1)
        dummy.text("A SERVIR\n")
        dummy.set(align="left", bold=False, width=1, height=1)
        moment = sale.date or datetime.now()
        dummy.text(f"{sale.ticket_number}  {moment:%H:%M}\n")
        dummy.text("-" * 24 + "\n")

        items = list(sale.items or [])
        for item in items:
            qty = format_quantity(item.quantity)
            name = (item.product_name or "").strip().upper()
            # Gras + majuscules = visible, hauteur normale = économe en papier.
            dummy.set(align="left", bold=True, width=1, height=1)
            dummy.text(f"{qty}x {name}\n")

        dummy.set(bold=False)
        dummy.text("-" * 24 + "\n")
        if feed_lines:
            dummy.text("\n" * feed_lines)
        if cut_mode != "none":
            escpos_mode = _CUT_MODES.get(cut_mode, "FULL")
            try:
                dummy.cut(mode=escpos_mode)
            except Exception:
                try:
                    dummy.cut()
                except Exception:
                    logger.debug("Coupe ESC/POS ignorée.", exc_info=True)
        return dummy.output
    except Exception:
        content = render_ticket_text(
            sale, shop, paper=paper, layout=TICKET_LAYOUT_KITCHEN
        )
        return _build_escpos_bytes(
            content,
            feed_lines=feed_lines,
            cut_mode=cut_mode,
            logo_path=None,
            paper=paper,
        )


def _build_escpos_bytes(
    content: str,
    feed_lines: int = DEFAULT_FEED_LINES,
    cut_mode: str = DEFAULT_CUT_MODE,
    logo_path: Optional[str] = None,
    paper: str = "80mm",
) -> bytes:
    """Génère le flux ESC/POS : logo + texte + avance papier + coupe.

    - ``logo_path`` : image du logo à imprimer en tête (facultatif) ;
    - ``feed_lines`` : lignes vides ajoutées après le contenu pour faire sortir
      entièrement le ticket au-delà du massicot / de la barre de découpe ;
    - ``cut_mode`` : ``"full"``, ``"partial"`` ou ``"none"``.
    """
    feed_lines = max(0, int(feed_lines))
    try:
        from escpos.printer import Dummy

        dummy = Dummy()
        # Logo centré en haut du ticket (best-effort : ignoré si non imprimable).
        logo = _load_logo_image(logo_path, paper)
        if logo is not None:
            try:
                dummy.set(align="center")
                dummy.image(logo)
                dummy.set(align="left")
            except Exception:
                logger.debug(
                    "Logo thermique ignoré par le générateur ESC/POS.",
                    exc_info=True,
                )
        dummy.text(content)
        if feed_lines:
            dummy.text("\n" * feed_lines)
        if cut_mode != "none":
            escpos_mode = _CUT_MODES.get(cut_mode, "FULL")
            try:
                dummy.cut(mode=escpos_mode)
            except Exception:
                try:
                    dummy.cut()
                except Exception:
                    logger.debug("Commande de coupe ESC/POS ignorée.", exc_info=True)
        return dummy.output
    except Exception:
        data = content.encode("utf-8", errors="replace")
        data += b"\n" * feed_lines
        if cut_mode != "none":
            data += b"\x1d\x56\x00"  # GS V 0 : coupe complète
        return data


def _print_windows(raw: bytes, printer_name: str) -> PrintResult:  # pragma: no cover
    """Envoie les octets bruts à une imprimante Windows (nom ou par défaut).

    Important : on refuse d'empiler un job si l'imprimante est hors ligne /
    en pause / en erreur. Sinon Windows garde les tickets en file et les
    imprime tous d'un coup au prochain rallumage.
    """
    try:
        import win32print
    except Exception as exc:
        return PrintResult(False, Path(), f"Module d'impression Windows absent : {exc}")

    target = printer_name or win32print.GetDefaultPrinter()
    if not target:
        return PrintResult(False, Path(), "Aucune imprimante Windows configurée.")

    # Pré-contrôle : ne pas alimenter la file si le périphérique est indisponible.
    preflight = _windows_printer_preflight(target)
    if preflight is not None:
        return preflight

    job_id = 0
    written = 0
    try:
        handle = win32print.OpenPrinter(target)
        try:
            job_id = win32print.StartDocPrinter(handle, 1, ("Ticket", None, "RAW"))
            win32print.StartPagePrinter(handle)
            written = win32print.WritePrinter(handle, raw) or 0
            win32print.EndPagePrinter(handle)
            win32print.EndDocPrinter(handle)
        finally:
            win32print.ClosePrinter(handle)
    except Exception as exc:
        if job_id:
            _windows_cancel_job(target, job_id)
        return PrintResult(False, Path(), f"Échec de l'impression Windows : {exc}")

    if int(written) < len(raw):
        _windows_cancel_job(target, job_id)
        return PrintResult(
            False,
            Path(),
            f"Envoi incomplet vers « {target} » "
            f"({written}/{len(raw)} octets). Vérifiez le câble USB / le pilote.",
        )

    # Court contrôle post-envoi : si le job reste bloqué (offline / erreur),
    # on l'annule pour éviter l'impression en rafale au redémarrage.
    blocked = _windows_job_blocked(target, job_id, timeout_s=2.5)
    if blocked:
        _windows_cancel_job(target, job_id)
        return PrintResult(
            False,
            Path(),
            f"L'imprimante « {target} » n'a pas accepté le ticket ({blocked}). "
            "Le job a été annulé pour ne pas s'accumuler dans la file Windows. "
            "Vérifiez que l'imprimante est allumée et connectée, puis réessayez.",
        )

    return PrintResult(
        True,
        Path(),
        f"Ticket envoyé à « {target} ». "
        "Si rien ne sort, vérifiez papier / câble (ne redémarrez pas pour « forcer »).",
    )


# Drapeaux Windows indiquant qu'il ne faut PAS empiler de nouveaux jobs.
_WIN_PRINTER_BAD = (
    0x00000001  # PAUSED
    | 0x00000002  # ERROR
    | 0x00000008  # PAPER_JAM
    | 0x00000010  # PAPER_OUT
    | 0x00000040  # PAPER_PROBLEM
    | 0x00000080  # OFFLINE
    | 0x00001000  # NOT_AVAILABLE
    | 0x00100000  # USER_INTERVENTION
    | 0x00400000  # DOOR_OPEN
)

_WIN_JOB_BAD = (
    0x00000002  # ERROR
    | 0x00000020  # OFFLINE
    | 0x00000040  # PAPEROUT
    | 0x00000200  # BLOCKED_DEVQ
    | 0x00000400  # USER_INTERVENTION
)


def windows_printer_status_reason(status: int) -> str:
    """Interprète GetPrinter Status (testable hors Windows). Chaîne vide = OK."""
    status = int(status or 0)
    if not (status & _WIN_PRINTER_BAD):
        return ""
    reasons = []
    if status & 0x00000080:
        reasons.append("hors ligne")
    if status & 0x00000001:
        reasons.append("en pause")
    if status & 0x00000010:
        reasons.append("plus de papier")
    if status & 0x00000002:
        reasons.append("en erreur")
    return ", ".join(reasons) or f"état 0x{status:X}"


def windows_job_status_reason(status: int) -> str:
    """Interprète EnumJobs Status. Chaîne vide = pas de blocage détecté."""
    status = int(status or 0)
    if not (status & _WIN_JOB_BAD):
        return ""
    if status & 0x00000020:
        return "hors ligne"
    if status & 0x00000040:
        return "plus de papier"
    if status & 0x00000002:
        return "erreur"
    return "bloqué"


def _windows_printer_preflight(printer_name: str) -> Optional[PrintResult]:
    """Refuse l'impression si l'imprimante Windows est clairement indisponible."""
    try:
        import win32print

        handle = win32print.OpenPrinter(printer_name)
        try:
            info = win32print.GetPrinter(handle, 2)
        finally:
            win32print.ClosePrinter(handle)
    except Exception as exc:
        return PrintResult(
            False,
            Path(),
            f"Impossible d'ouvrir « {printer_name} » : {exc}",
        )

    reason = windows_printer_status_reason(int(info.get("Status", 0) or 0))
    if reason:
        return PrintResult(
            False,
            Path(),
            f"Imprimante « {printer_name} » indisponible ({reason}). "
            "Allumez-la / reconnectez le USB avant de réimprimer. "
            "Aucun ticket n'a été mis en file d'attente.",
        )
    return None


def _windows_job_blocked(printer_name: str, job_id: int, timeout_s: float = 2.5) -> str:
    """Retourne un motif si le job est bloqué ; chaîne vide sinon."""
    if not job_id:
        return ""
    import time

    try:
        import win32print
    except Exception:
        return ""

    deadline = time.monotonic() + max(0.5, float(timeout_s))
    while time.monotonic() < deadline:
        try:
            handle = win32print.OpenPrinter(printer_name)
            try:
                jobs = win32print.EnumJobs(handle, 0, -1, 1)
            finally:
                win32print.ClosePrinter(handle)
        except Exception:
            return ""
        match = next((j for j in jobs if int(j.get("JobId", 0)) == int(job_id)), None)
        if match is None:
            # Job disparu de la file → traité (imprimé ou consommé).
            return ""
        reason = windows_job_status_reason(int(match.get("Status", 0) or 0))
        if reason:
            return reason
        # Encore en cours : on laisse une chance courte, puis on considère OK.
        time.sleep(0.25)
    return ""


def _windows_cancel_job(printer_name: str, job_id: int) -> None:
    if not job_id:
        return
    try:
        import win32print

        handle = win32print.OpenPrinter(printer_name)
        try:
            win32print.SetJob(handle, int(job_id), 0, None, win32print.JOB_CONTROL_DELETE)
        finally:
            win32print.ClosePrinter(handle)
    except Exception:
        logger.debug("Annulation du job d'impression impossible.", exc_info=True)


def purge_printer_queue(printer_name: Optional[str] = None) -> PrintResult:
    """Vide la file d'attente Windows de l'imprimante (évite la rafale au reboot)."""
    if not sys.platform.startswith("win"):  # pragma: no cover
        return PrintResult(
            False, Path(), "La purge de file n'est disponible que sous Windows."
        )
    try:
        import win32print
    except Exception as exc:
        return PrintResult(False, Path(), f"Module d'impression Windows absent : {exc}")

    name = (printer_name or "").strip() or settings_service.get_setting("printer_name", "")
    target = name or win32print.GetDefaultPrinter()
    if not target:
        return PrintResult(False, Path(), "Aucune imprimante à purger.")
    try:
        handle = win32print.OpenPrinter(target)
        try:
            jobs = win32print.EnumJobs(handle, 0, -1, 1)
            cancelled = 0
            for job in jobs:
                job_id = int(job.get("JobId", 0) or 0)
                if not job_id:
                    continue
                try:
                    win32print.SetJob(
                        handle, job_id, 0, None, win32print.JOB_CONTROL_DELETE
                    )
                    cancelled += 1
                except Exception:
                    logger.debug("Job %s non annulé.", job_id, exc_info=True)
        finally:
            win32print.ClosePrinter(handle)
    except Exception as exc:
        return PrintResult(False, Path(), f"Impossible de purger « {target} » : {exc}")
    return PrintResult(
        True,
        Path(),
        f"File d'attente de « {target} » vidée ({cancelled} job(s) annulé(s)).",
    )


def _print_posix(raw: bytes, printer_name: str) -> PrintResult:
    """Impression sous Linux/macOS : périphérique brut ou CUPS (lp)."""
    # 1) Chemin de périphérique explicite (ex. /dev/usb/lp0).
    if printer_name and ("/" in printer_name or printer_name.startswith("\\")):
        try:
            with open(printer_name, "wb") as device:
                device.write(raw)
                device.flush()
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
    """Imprime réellement le ticket / la facture et retourne le résultat.

    - Format thermique (58/80 mm) : copie texte + envoi ESC/POS RAW.
    - Format ``demi-A4`` : PDF 210×148,5 mm + impression bureau (non RAW).
    """
    from app.printers.half_a4_invoice import is_half_a4, print_half_a4_invoice

    shop = shop or settings_service.get_shop_info()
    if is_half_a4(paper):
        # Archive texte + impression PDF facture.
        text_path = save_ticket_file(sale, shop, paper)
        result = print_half_a4_invoice(sale, shop=shop, printer_name=printer_name)
        if result.file_path and result.file_path.suffix.lower() == ".pdf":
            # Conserve aussi le chemin texte dans le message si utile.
            if text_path and text_path.exists():
                result.message = (
                    f"{result.message}\nCopie texte : {text_path}"
                ).strip()
        elif not result.file_path:
            result.file_path = text_path
        return result

    path = save_ticket_file(sale, shop, paper)
    layout = _resolve_layout(None)
    if layout == TICKET_LAYOUT_KITCHEN:
        # Bon serveur : flux ESC/POS dédié (gras, sans logo ni double hauteur).
        result = _send_content(
            "",
            printer_name,
            logo_path=None,
            paper=paper,
            sale=sale,
            layout=TICKET_LAYOUT_KITCHEN,
        )
    else:
        content = render_ticket_text(sale, shop, paper)
        result = _send_content(
            content, printer_name, logo_path=shop.logo_path, paper=paper
        )
    result.file_path = path
    return result


def _send_content(
    content: str,
    printer_name: Optional[str] = None,
    logo_path: Optional[str] = None,
    paper: str = "80mm",
    sale=None,
    layout: Optional[str] = None,
) -> PrintResult:
    """Envoie un contenu déjà formaté à l'imprimante selon les réglages courants."""
    printer_name = (
        printer_name
        if printer_name is not None
        else settings_service.get_setting("printer_name", "")
    ).strip()

    # Réglages d'avance papier / coupe (configurables dans les Paramètres).
    try:
        feed_lines = int(
            settings_service.get_setting("ticket_feed_lines", str(DEFAULT_FEED_LINES))
        )
    except (TypeError, ValueError):
        feed_lines = DEFAULT_FEED_LINES
    cut_mode = settings_service.get_setting("ticket_cut_mode", DEFAULT_CUT_MODE)
    if cut_mode not in ("full", "partial", "none"):
        cut_mode = DEFAULT_CUT_MODE

    # Bon serveur : moins d'avance papier (contenu déjà très court).
    if layout == TICKET_LAYOUT_KITCHEN and sale is not None:
        feed_lines = min(feed_lines, 2)
        raw = _build_escpos_serveur_bytes(
            sale,
            feed_lines=feed_lines,
            cut_mode=cut_mode,
            logo_path=None,
            paper=paper,
        )
    else:
        raw = _build_escpos_bytes(
            content,
            feed_lines=feed_lines,
            cut_mode=cut_mode,
            logo_path=logo_path,
            paper=paper,
        )

    if sys.platform.startswith("win"):
        result = _print_windows(raw, printer_name)
    else:
        result = _print_posix(raw, printer_name)

    if not result.printed and not result.message:
        result.message = "Aucune imprimante configurée."
    return result


def print_test_page(printer_name: Optional[str] = None) -> PrintResult:
    """Imprime une page de test (pour régler avance papier / coupe par modèle)."""
    shop = settings_service.get_shop_info()
    paper = settings_service.get_setting("ticket_format", "80mm")
    width = WIDTH_CHARS.get(paper, 48)

    lines = [
        _center(shop.name or "Gestion Commerciale", width),
        _line("=", width),
        _center("PAGE DE TEST", width),
        _center(f"Format {paper}", width),
        _line("-", width),
        "Si vous lisez ces lignes entièrement",
        "et que le papier est coupé,",
        "l'imprimante est bien configurée.",
        _line("-", width),
        _center(datetime.now().strftime("%d/%m/%Y %H:%M"), width),
    ]
    return _send_content(
        "\n".join(lines), printer_name, logo_path=shop.logo_path, paper=paper
    )


def render_debt_payment_text(
    *,
    client_name: str,
    amount: float,
    payment_method: str,
    remaining_after: float,
    note: str = "",
    cashier: str = "",
    payment_id: Optional[int] = None,
    shop=None,
    paper: str = "80mm",
) -> str:
    """Construit le reçu texte d'un règlement de dette client."""
    shop = shop or settings_service.get_shop_info()
    # Force thermique pour les reçus dette (pas de demi-A4 ici).
    if paper not in ("58mm", "80mm"):
        paper = "80mm"
    width = WIDTH_CHARS.get(paper, 48)
    currency = shop.currency or "FCFA"
    lines = [
        _center(shop.name or "Commerce", width),
        _line("=", width),
        _center("RECU REGLEMENT DETTE", width),
        _line("-", width),
        _row("Date", datetime.now().strftime("%d/%m/%Y %H:%M"), width),
    ]
    if payment_id:
        lines.append(_row("N°", str(payment_id), width))
    if cashier:
        lines.append(_row("Caissier", cashier[: width // 2], width))
    lines.append(_row("Client", (client_name or "—")[: width // 2], width))
    lines.append(_line("-", width))
    lines.append(_row("Montant payé", format_money(amount, currency), width))
    lines.append(_row("Mode", payment_method or "Espèces", width))
    lines.append(_row("Reste dû", format_money(remaining_after, currency), width))
    if note:
        lines.append(_line("-", width))
        lines.append(f"Note : {note[: width * 2]}")
    lines.append(_line("=", width))
    lines.append(_center("Merci", width))
    lines.append("")
    return "\n".join(lines)


def save_debt_payment_file(
    content: str, payment_id: Optional[int] = None
) -> Path:
    """Archive le reçu de règlement dans le dossier tickets."""
    config.ensure_directories()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"dette_paye_{payment_id or 'x'}_{stamp}"
    path = config.TICKET_DIR / f"{base}.txt"
    counter = 1
    while path.exists():
        path = config.TICKET_DIR / f"{base}_{counter}.txt"
        counter += 1
    path.write_text(content, encoding="utf-8")
    return path


def print_debt_payment(
    *,
    client_name: str,
    amount: float,
    payment_method: str,
    remaining_after: float,
    note: str = "",
    cashier: str = "",
    payment_id: Optional[int] = None,
    printer_name: Optional[str] = None,
) -> PrintResult:
    """Imprime (et archive) un reçu de règlement de dette."""
    shop = settings_service.get_shop_info()
    paper = settings_service.get_setting("ticket_format", "80mm")
    if paper not in ("58mm", "80mm"):
        paper = "80mm"
    content = render_debt_payment_text(
        client_name=client_name,
        amount=amount,
        payment_method=payment_method,
        remaining_after=remaining_after,
        note=note,
        cashier=cashier,
        payment_id=payment_id,
        shop=shop,
        paper=paper,
    )
    path = save_debt_payment_file(content, payment_id=payment_id)
    printer = printer_name or settings_service.get_setting("printer_name", "")
    result = _send_content(
        content, printer or None, logo_path=shop.logo_path, paper=paper
    )
    result.file_path = path
    if not result.printed:
        result.message = (
            f"{result.message}\nCopie : {path}".strip()
            if result.message
            else f"Reçu enregistré : {path}"
        )
    return result

