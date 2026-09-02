"""Helpers de tableau ASCII pour tickets thermiques (facture type grille)."""

from __future__ import annotations


def table_column_widths(width: int) -> tuple[int, int, int, int]:
    """Largeurs Designation / Qte / Prix / Montant (hors séparateurs)."""
    # Ligne : |des|qte|prix|mt| → 5 caractères de bordure.
    usable = max(16, width - 5)
    if width <= 32:
        qte, prix, montant = 3, 6, 7
    else:
        qte, prix, montant = 4, 8, 9
    des = max(6, usable - qte - prix - montant)
    # Recaler si dépasse.
    while des + qte + prix + montant + 5 > width and des > 6:
        des -= 1
    while des + qte + prix + montant + 5 > width and montant > 5:
        montant -= 1
    return des, qte, prix, montant


def _cell(text: str, width: int, align: str = "left") -> str:
    text = (text or "")[:width]
    if align == "right":
        return text.rjust(width)
    if align == "center":
        return text.center(width)
    return text.ljust(width)


def table_rule(width: int, cols: tuple[int, int, int, int]) -> str:
    d, q, p, m = cols
    line = "+" + ("-" * d) + "+" + ("-" * q) + "+" + ("-" * p) + "+" + ("-" * m) + "+"
    return line[:width].ljust(width)[:width] if len(line) < width else line[:width]


def table_header_row(width: int, cols: tuple[int, int, int, int]) -> str:
    d, q, p, m = cols
    if width <= 32:
        labels = ("Article", "Qt", "Prix", "Total")
    else:
        labels = ("Designation", "Qte", "Prix", "Montant")
    return (
        "|"
        + _cell(labels[0], d)
        + "|"
        + _cell(labels[1], q, "center")
        + "|"
        + _cell(labels[2], p, "right")
        + "|"
        + _cell(labels[3], m, "right")
        + "|"
    )[:width]


def table_data_row(
    width: int,
    cols: tuple[int, int, int, int],
    designation: str,
    qty: str,
    price: str,
    amount: str,
) -> str:
    d, q, p, m = cols
    return (
        "|"
        + _cell(designation, d)
        + "|"
        + _cell(qty, q, "center")
        + "|"
        + _cell(price, p, "right")
        + "|"
        + _cell(amount, m, "right")
        + "|"
    )[:width]


def table_total_row(width: int, cols: tuple[int, int, int, int], amount: str) -> str:
    """Ligne TOTAL fusionnée sous le tableau."""
    d, q, p, m = cols
    left_w = d + 1 + q + 1 + p
    return ("|" + _cell("TOTAL", left_w) + "|" + _cell(amount, m, "right") + "|")[:width]


def table_total_rule(width: int, cols: tuple[int, int, int, int]) -> str:
    d, q, p, m = cols
    left_w = d + 1 + q + 1 + p
    line = "+" + ("-" * left_w) + "+" + ("-" * m) + "+"
    return line[:width]


def frame_text(text: str, width: int) -> list[str]:
    """Encadre un texte (montant en lettres) dans un rectangle ASCII."""
    inner_w = max(4, width - 2)
    chunks: list[str] = []
    remaining = (text or "").strip()
    if not remaining:
        remaining = "—"
    while remaining:
        chunks.append(remaining[:inner_w])
        remaining = remaining[inner_w:]
    lines = ["/" + ("-" * inner_w) + "\\"]
    for chunk in chunks:
        lines.append("|" + chunk.ljust(inner_w)[:inner_w] + "|")
    lines.append("\\" + ("-" * inner_w) + "/")
    return [ln[:width] for ln in lines]