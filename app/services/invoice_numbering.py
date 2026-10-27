"""Numéro de facture séquentiel simple : 00001, 00002, …

Attribué à la première génération de facture d'une vente, puis conservé
(la même vente garde toujours le même numéro). Indépendant du numéro de ticket.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SETTING_COUNTER = "invoice_counter"
WIDTH = 5


def format_number(value: int) -> str:
    return f"{int(value):0{WIDTH}d}"


def invoice_number(sale) -> str:
    """Numéro de facture de ``sale`` (l'attribue si besoin). Aperçu → 00001."""
    existing = str(getattr(sale, "invoice_number", "") or "").strip()
    if existing:
        return existing
    sale_id = getattr(sale, "id", None)
    if not isinstance(sale_id, int):
        return format_number(1)  # aperçu / vente fictive
    try:
        from app.database.connection import session_scope
        from app.models.sale import Sale
        from app.services import settings_service

        with session_scope() as session:
            row = session.get(Sale, sale_id)
            if row is None:
                return format_number(1)
            if not (row.invoice_number or "").strip():
                try:
                    counter = int(settings_service.get_setting(SETTING_COUNTER, "0") or 0)
                except ValueError:
                    counter = 0
                counter += 1
                row.invoice_number = format_number(counter)
                settings_service.set_setting(SETTING_COUNTER, str(counter))
            number = row.invoice_number
        try:
            sale.invoice_number = number
        except Exception:
            pass
        return number
    except Exception:
        logger.warning("Numéro de facture indisponible, repli sur le numéro de ticket.", exc_info=True)
        return str(getattr(sale, "ticket_number", ""))
