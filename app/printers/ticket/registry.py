"""Registre des designs + résolution des IDs depuis les paramètres."""

from __future__ import annotations

from typing import Optional

from app.printers.ticket.designs.base import TicketDesign
from app.printers.ticket.designs.client_designs import CLIENT_DESIGN_CLASSES
from app.printers.ticket.designs.kitchen_designs import KITCHEN_DESIGN_CLASSES
from app.services import settings_service

# Migration depuis l'ancien paramètre ``ticket_layout``.
_LEGACY_LAYOUT_MAP = {
    "classic": "classic",
    "compact": "compact",
    "table": "terminal",
    "kitchen": "serveur",
}

_REGISTRY: dict[str, TicketDesign] = {}
for cls in (*CLIENT_DESIGN_CLASSES, *KITCHEN_DESIGN_CLASSES):
    inst = cls()
    _REGISTRY[inst.id] = inst

CLIENT_DESIGNS = tuple(
    _REGISTRY[c.id] for c in CLIENT_DESIGN_CLASSES if c.id != "kitchen"
)
KITCHEN_DESIGNS = tuple(
    d
    for d in (_REGISTRY[c.id] for c in KITCHEN_DESIGN_CLASSES)
    if d.id != "kitchen"  # alias caché dans l'UI
)


def list_designs(category: Optional[str] = None) -> list[TicketDesign]:
    if category == "client":
        return list(CLIENT_DESIGNS)
    if category == "kitchen":
        return list(KITCHEN_DESIGNS)
    return list(CLIENT_DESIGNS) + list(KITCHEN_DESIGNS)


def get_design(design_id: str) -> TicketDesign:
    if design_id in _REGISTRY:
        return _REGISTRY[design_id]
    mapped = _LEGACY_LAYOUT_MAP.get(design_id)
    if mapped and mapped in _REGISTRY:
        return _REGISTRY[mapped]
    return _REGISTRY["classic"]


def resolve_client_design_id(explicit: Optional[str] = None) -> str:
    if explicit:
        design = get_design(explicit)
        return design.id if design.category == "client" or explicit in _REGISTRY else design.id
    stored = settings_service.get_setting("ticket_client_design", "")
    if stored and stored in _REGISTRY and _REGISTRY[stored].category == "client":
        return stored
    # Migration depuis ticket_layout.
    legacy = settings_service.get_setting("ticket_layout", "classic")
    mapped = _LEGACY_LAYOUT_MAP.get(legacy, "classic")
    if mapped in _REGISTRY and _REGISTRY[mapped].category == "client":
        return mapped
    return "classic"


def resolve_kitchen_design_id(explicit: Optional[str] = None) -> str:
    if explicit:
        design = get_design(explicit)
        return design.id
    stored = settings_service.get_setting("ticket_kitchen_design", "")
    if stored and stored in _REGISTRY and _REGISTRY[stored].category == "kitchen":
        return stored
    legacy = settings_service.get_setting("ticket_layout", "")
    if legacy in ("kitchen",) or _LEGACY_LAYOUT_MAP.get(legacy) == "serveur":
        # Ancien choix unique « kitchen » → bon serveur.
        if legacy == "kitchen":
            return "serveur"
    return "serveur"


def resolve_design_id(
    explicit: Optional[str] = None, *, role: str = "client"
) -> str:
    if role == "kitchen":
        return resolve_kitchen_design_id(explicit)
    return resolve_client_design_id(explicit)
