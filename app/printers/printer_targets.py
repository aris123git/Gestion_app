"""Résolution des imprimantes ticket (thermique) vs facture (encre / bureau)."""

from __future__ import annotations

from typing import Literal, Optional, Tuple

from app.printers.half_a4_invoice import PAPER_HALF_A4, is_half_a4
from app.services import settings_service

# Clés de réglages.
SETTING_THERMAL_PRINTER = "printer_name"  # historique : ticket 58/80 mm
SETTING_INVOICE_PRINTER = "invoice_printer_name"  # facture demi-A4 (encre/laser)
SETTING_TICKET_FORMAT = "ticket_format"

PrinterKind = Literal["thermique", "encre"]


def get_thermal_printer_name() -> str:
    """Imprimante ticket thermique (ESC/POS)."""
    return (settings_service.get_setting(SETTING_THERMAL_PRINTER, "") or "").strip()


def get_invoice_printer_name() -> str:
    """Imprimante facture papier (jet d'encre / laser).

    Si non configurée, retombe sur l'imprimante thermique pour ne pas casser
    les installations existantes (une seule imprimante).
    """
    dedicated = (
        settings_service.get_setting(SETTING_INVOICE_PRINTER, "") or ""
    ).strip()
    if dedicated:
        return dedicated
    return get_thermal_printer_name()


def printer_for_paper(paper: str) -> str:
    """Retourne le nom d'imprimante à utiliser selon le format choisi."""
    if is_half_a4(paper):
        return get_invoice_printer_name()
    return get_thermal_printer_name()


def get_default_paper() -> str:
    """Format papier préféré (``80mm`` / ``58mm`` / ``demi-A4``)."""
    return (settings_service.get_setting(SETTING_TICKET_FORMAT, "80mm") or "80mm").strip()


def get_default_printer_kind() -> PrinterKind:
    """Type d'imprimante préféré après encaissement : thermique ou encre."""
    return "encre" if is_half_a4(get_default_paper()) else "thermique"


def paper_for_kind(kind: str, thermal_width: str = "80mm") -> str:
    """Construit la valeur ``ticket_format`` depuis le type + largeur thermique."""
    if (kind or "").strip().lower() == "encre":
        return PAPER_HALF_A4
    width = (thermal_width or "80mm").strip()
    return "58mm" if width == "58mm" else "80mm"


def describe_destinations() -> Tuple[str, str]:
    """Libellés d'affichage (thermique, facture) pour l'UI caissier."""
    thermal = get_thermal_printer_name() or "(imprimante par défaut du système)"
    invoice = (
        settings_service.get_setting(SETTING_INVOICE_PRINTER, "") or ""
    ).strip()
    if not invoice:
        invoice = f"{thermal} (même que ticket)"
    return thermal, invoice


def set_printers(
    thermal_name: Optional[str] = None,
    invoice_name: Optional[str] = None,
) -> None:
    if thermal_name is not None:
        settings_service.set_setting(SETTING_THERMAL_PRINTER, thermal_name.strip())
    if invoice_name is not None:
        settings_service.set_setting(SETTING_INVOICE_PRINTER, invoice_name.strip())


def set_default_print_preference(kind: str, thermal_width: str = "80mm") -> str:
    """Enregistre le type d'imprimante par défaut ; retourne le ``ticket_format``."""
    paper = paper_for_kind(kind, thermal_width)
    settings_service.set_setting(SETTING_TICKET_FORMAT, paper)
    return paper
