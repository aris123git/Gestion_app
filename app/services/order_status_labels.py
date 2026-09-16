"""Libellés statuts commande (affichage PC = app mobile)."""

from __future__ import annotations

from app.models.open_order import (
    STATUS_CANCELLED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_SERVED,
    STATUS_UNPAID,
)

_LABELS = {
    STATUS_OPEN: "En cours",
    STATUS_UNPAID: "Non payée",
    STATUS_PAID: "Payée",
    STATUS_CANCELLED: "Annulée",
    STATUS_SERVED: "Servie",
    "EN_COURS": "En cours",
    "NON_PAYEE": "Non payée",
    "PAYEE": "Payée",
    "ANNULEE": "Annulée",
}


def label_for_status(status: str) -> str:
    return _LABELS.get(status or "", status or "—")
