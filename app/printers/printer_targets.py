"""Résolution des imprimantes ticket (thermique) vs facture (encre / bureau)."""

from __future__ import annotations

from typing import Optional, Tuple

from app.printers.half_a4_invoice import is_half_a4
from app.services import settings_service

# Clés de réglages.
SETTING_THERMAL_PRINTER = "printer_name"  # historique : ticket 58/80 mm
SETTING_INVOICE_PRINTER = "invoice_printer_name"  # facture demi-A4 (encre/laser)
SETTING_TICKET_FORMAT = "ticket_format"


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
