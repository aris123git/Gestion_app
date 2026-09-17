"""Libellés statuts commande / table (affichage PC = app mobile)."""

from __future__ import annotations

from app.models.dining_table import (
    STATUS_CLEANING,
    STATUS_FREE,
    STATUS_OCCUPIED,
    STATUS_RESERVED,
)
from app.models.open_order import (
    STATUS_CANCELLED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_SERVED,
    STATUS_UNPAID,
)

_ORDER_LABELS = {
    STATUS_OPEN: "En cours",
    STATUS_UNPAID: "Non payée",
    STATUS_PAID: "Payée",
    STATUS_CANCELLED: "Annulée",
    STATUS_SERVED: "Servie",
    "EN_COURS": "En cours",
    "NON_PAYEE": "Non payée",
    "PAYEE": "Payée",
    "ANNULEE": "Annulée",
    "SERVIE": "Servie",
}

_TABLE_LABELS = {
    STATUS_FREE: "Libre",
    STATUS_OCCUPIED: "Occupée",
    STATUS_RESERVED: "Réservée",
    STATUS_CLEANING: "À nettoyer",
}


def label_for_status(status: str) -> str:
    return _ORDER_LABELS.get(status or "", status or "—")


def label_for_table_status(status: str) -> str:
    return _TABLE_LABELS.get(status or "", status or "—")
