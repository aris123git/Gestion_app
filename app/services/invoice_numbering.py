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


def _sequential(sale, attr: str, counter_key: str) -> str:
    existing = str(getattr(sale, attr, "") or "").strip()
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
            if not (getattr(row, attr) or "").strip():
                try:
                    counter = int(settings_service.get_setting(counter_key, "0") or 0)
                except ValueError:
                    counter = 0
                # Jamais en dessous du plus grand numéro déjà attribué (compteur réinitialisé, base restaurée…).
                from sqlalchemy import func, select

                column = getattr(Sale, attr)
                numeric = [int(v) for v in session.scalars(select(column).where(column != "").order_by(column.desc()).limit(50)) if str(v).isdigit()]
                counter = max([counter, *numeric])
                counter += 1
                setattr(row, attr, format_number(counter))
                settings_service.set_setting(counter_key, str(counter))
            number = getattr(row, attr)
        try:
            setattr(sale, attr, number)
        except Exception:
            pass
        return number
    except Exception:
        logger.warning("Numéro séquentiel indisponible, repli sur le numéro de ticket.", exc_info=True)
        return str(getattr(sale, "ticket_number", ""))


def invoice_number(sale) -> str:
    """Numéro de facture de ``sale`` (l'attribue si besoin). Aperçu → 00001."""
    return _sequential(sale, "invoice_number", SETTING_COUNTER)


def pickup_number(sale) -> str:
    """Numéro de bon d'enlèvement (BE N°), séquence indépendante des factures."""
    return _sequential(sale, "pickup_number", "pickup_counter")


def delivery_number(sale) -> str:
    """Numéro de bon de livraison (BL N°), séquence indépendante."""
    return _sequential(sale, "delivery_number", "delivery_counter")
