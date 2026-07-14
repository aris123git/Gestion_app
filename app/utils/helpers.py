"""Fonctions d'aide : formatage monétaire, dates, nombres."""

from __future__ import annotations

from datetime import datetime


def format_money(amount, currency: str = "FCFA") -> str:
    """Formate un montant avec séparateur de milliers et devise."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        value = 0.0
    formatted = f"{value:,.0f}".replace(",", " ")
    return f"{formatted} {currency}".strip()


def format_quantity(value) -> str:
    """Affiche une quantité sans décimales inutiles (3 -> '3', 1.5 -> '1.5')."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


def to_float(value, default: float = 0.0) -> float:
    """Convertit une saisie utilisateur en float de façon tolérante."""
    if value is None:
        return default
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return default


def generate_ticket_number(sequence: int, moment: datetime | None = None) -> str:
    """Construit un numéro de ticket lisible : ``T-YYYYMMDD-000123``."""
    moment = moment or datetime.now()
    return f"T-{moment:%Y%m%d}-{sequence:06d}"


def format_datetime(moment: datetime | None) -> str:
    if not moment:
        return ""
    return moment.strftime("%d/%m/%Y %H:%M")


def format_date(moment: datetime | None) -> str:
    if not moment:
        return ""
    return moment.strftime("%d/%m/%Y")
