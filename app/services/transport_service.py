"""Chauffeurs et camions (références) : listes réglées dans Paramètres, choisies sur les ventes et enlèvements.

Information interne : jamais imprimée sur les tickets, factures ou bons ; conservée pour consultation ultérieure.
"""

from __future__ import annotations

import json
from typing import List

from app.database.connection import session_scope
from app.services import settings_service

KEYS = {"driver": "transport_drivers", "truck": "transport_trucks"}


def _load(kind: str) -> List[str]:
    try:
        data = json.loads(settings_service.get_setting(KEYS[kind], "[]") or "[]")
    except ValueError:
        return []
    return [str(x).strip() for x in data if str(x).strip()]


def _save(kind: str, names: List[str]) -> None:
    clean: List[str] = []
    for n in names:
        n = str(n).strip()
        if n and n.casefold() not in {c.casefold() for c in clean}:
            clean.append(n)
    settings_service.set_setting(KEYS[kind], json.dumps(clean, ensure_ascii=False))


def list_names(kind: str) -> List[str]:
    """``kind`` : « driver » (chauffeurs) ou « truck » (n° / référence de camion)."""
    return _load(kind)


def add(kind: str, name: str) -> None:
    _save(kind, _load(kind) + [name])


def remove(kind: str, name: str) -> None:
    _save(kind, [n for n in _load(kind) if n.casefold() != str(name).strip().casefold()])


def set_sale_transport(sale_id: int, driver: str = "", truck: str = "") -> None:
    """Enregistre (en texte, pour rester lisible même si la liste change) le chauffeur / camion d'une vente."""
    from app.models.sale import Sale

    with session_scope() as session:
        sale = session.get(Sale, sale_id)
        if sale is None:
            raise ValueError("Vente introuvable.")
        sale.driver_name = (driver or "").strip()
        sale.truck_ref = (truck or "").strip()


def get_sale_transport(sale_id: int) -> tuple[str, str]:
    from app.models.sale import Sale

    with session_scope() as session:
        sale = session.get(Sale, sale_id)
        return (sale.driver_name or "", sale.truck_ref or "") if sale else ("", "")
