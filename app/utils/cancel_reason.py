"""Validation du motif d'annulation de vente."""

from __future__ import annotations

from typing import Optional

MIN_CANCEL_REASON_LETTERS = 10


def count_letters(text: str) -> int:
    """Nombre de lettres Unicode (ignore chiffres, espaces, ponctuation)."""
    return sum(1 for ch in (text or "") if ch.isalpha())


def validate_cancel_reason(text: str) -> Optional[str]:
    """Retourne le motif normalisé, ou ``None`` s'il est invalide."""
    reason = (text or "").strip()
    if count_letters(reason) < MIN_CANCEL_REASON_LETTERS:
        return None
    return reason
