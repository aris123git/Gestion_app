"""Helpers de tableau fluide pour tickets thermiques (facture type grille).

Traits continus (Unicode box-drawing) + coins arrondis pour le cadre
du montant en lettres. Compatible aperçu texte et ESC/POS UTF-8.
"""

from __future__ import annotations

# Traits continus (table).
H, V = "─", "│"
TL, TR, BL, BR = "┌", "┐", "└", "┘"
T, B, L, R, X = "┬", "┴", "├", "┤", "┼"

# Coins arrondis (pastille montant en lettres).
RTL, RTR, RBL, RBR = "╭", "╮", "╰", "╯"


def table_column_widths(width: int) -> tuple[int, int, int, int]:
    """Largeurs Designation / Qte / Prix / Montant (hors séparateurs)."""
    usable = max(16, width - 5)
    if width <= 32:
        qte, prix, montant = 3, 6, 7
    else:
        qte, prix, montant = 4, 8, 9
    des = max(6, usable - qte - prix - montant)
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


def _rule(cols: tuple[int, int, int, int], left: str, mid: str, right: str) -> str:
    d, q, p, m = cols
    return left + (H * d) + mid + (H * q) + mid + (H * p) + mid + (H * m) + right


def table_top(width: int, cols: tuple[int, int, int, int]) -> str:
    return _rule(cols, TL, T, TR)[:width]


def table_mid(width: int, cols: tuple[int, int, int, int]) -> str:
    return _rule(cols, L, X, R)[:width]


def table_bottom(width: int, cols: tuple[int, int, int, int]) -> str:
    return _rule(cols, BL, B, BR)[:width]


# Alias rétrocompat (anciens tests / appels).
def table_rule(width: int, cols: tuple[int, int, int, int]) -> str:
    return table_mid(width, cols)


def table_header_row(width: int, cols: tuple[int, int, int, int]) -> str:
    d, q, p, m = cols
    if width <= 32:
        labels = ("Article", "Qt", "Prix", "Total")
    else:
        labels = ("Designation", "Qte", "Prix", "Montant")
    return (
        V
        + _cell(labels[0], d)
        + V
        + _cell(labels[1], q, "center")
        + V
        + _cell(labels[2], p, "right")
        + V
        + _cell(labels[3], m, "right")
        + V
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
        V
        + _cell(designation, d)
        + V
        + _cell(qty, q, "center")
        + V
        + _cell(price, p, "right")
        + V
        + _cell(amount, m, "right")
        + V
    )[:width]


def table_total_row(width: int, cols: tuple[int, int, int, int], amount: str) -> str:
    """Ligne TOTAL fusionnée (Designation+Qte+Prix) | Montant."""
    d, q, p, m = cols
    left_w = d + 1 + q + 1 + p
    return (V + _cell("TOTAL", left_w) + V + _cell(amount, m, "right") + V)[:width]


def table_total_top(width: int, cols: tuple[int, int, int, int]) -> str:
    """Séparateur au-dessus du TOTAL (fusionné à gauche)."""
    d, q, p, m = cols
    left_w = d + 1 + q + 1 + p
    return (L + (H * left_w) + X + (H * m) + R)[:width]


def table_total_bottom(width: int, cols: tuple[int, int, int, int]) -> str:
    d, q, p, m = cols
    left_w = d + 1 + q + 1 + p
    return (BL + (H * left_w) + B + (H * m) + BR)[:width]


def table_total_rule(width: int, cols: tuple[int, int, int, int]) -> str:
    """Alias rétrocompat → bas du bloc total."""
    return table_total_bottom(width, cols)


def frame_text(text: str, width: int, *, rounded: bool = True) -> list[str]:
    """Encadre un texte (montant en lettres) — coins arrondis par défaut."""
    inner_w = max(4, width - 2)
    chunks: list[str] = []
    remaining = (text or "").strip()
    if not remaining:
        remaining = "—"
    while remaining:
        chunks.append(remaining[:inner_w])
        remaining = remaining[inner_w:]
    if rounded:
        top = RTL + (H * inner_w) + RTR
        bot = RBL + (H * inner_w) + RBR
        side = V
    else:
        top = TL + (H * inner_w) + TR
        bot = BL + (H * inner_w) + BR
        side = V
    lines = [top]
    for chunk in chunks:
        lines.append(side + chunk.ljust(inner_w)[:inner_w] + side)
    lines.append(bot)
    return [ln[:width] for ln in lines]
