"""Helpers de tableau facture — modèle photo HARD SARL.

Tableau encadré avec séparateurs verticaux (Designation | Qte | Prix | Montant),
TOTAL hors cadre avec soulignement du montant uniquement,
cadre arrondi pour le montant en lettres.
"""

from __future__ import annotations

H, V = "─", "│"
TL, TR, BL, BR = "┌", "┐", "└", "┘"
T, B, LJ, RJ, X = "┬", "┴", "├", "┤", "┼"
RTL, RTR, RBL, RBR = "╭", "╮", "╰", "╯"


def table_column_widths(width: int) -> tuple[int, int, int, int]:
    """Largeurs internes Designation / Qte / Prix / Montant (hors │)."""
    # 5 traits verticaux → width - 5 = somme des colonnes.
    usable = max(14, width - 5)
    if width <= 32:
        qte, prix, montant = 3, 6, 7
    else:
        qte, prix, montant = 4, 8, 9
    des = max(5, usable - qte - prix - montant)
    while des + qte + prix + montant + 5 > width and des > 5:
        des -= 1
    while des + qte + prix + montant + 5 > width and montant > 5:
        montant -= 1
    while des + qte + prix + montant + 5 > width and prix > 4:
        prix -= 1
    return des, qte, prix, montant


def _cell(text: str, w: int, align: str = "left") -> str:
    text = (text or "")[:w]
    if align == "right":
        return text.rjust(w)
    if align == "center":
        return text.center(w)
    return text.ljust(w)


def _rule(cols: tuple[int, int, int, int], left: str, mid: str, right: str) -> str:
    d, q, p, m = cols
    return left + (H * d) + mid + (H * q) + mid + (H * p) + mid + (H * m) + right


def table_top(width: int, cols: tuple[int, int, int, int]) -> str:
    return _rule(cols, TL, T, TR)[:width]


def table_mid(width: int, cols: tuple[int, int, int, int]) -> str:
    return _rule(cols, LJ, X, RJ)[:width]


def table_bottom(width: int, cols: tuple[int, int, int, int]) -> str:
    return _rule(cols, BL, B, BR)[:width]


def table_header_row(width: int, cols: tuple[int, int, int, int]) -> str:
    d, q, p, m = cols
    # Libellés du modèle photo (sans accent sur Designation).
    if width <= 32:
        labels = ("Article", "Qte", "Prix", "Montant")
    else:
        labels = ("Designation", "Qte", "Prix", "Montant")
    return (
        V
        + _cell(labels[0], d)
        + V
        + _cell(labels[1], q, "right")
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
        + _cell(qty, q, "right")
        + V
        + _cell(price, p, "right")
        + V
        + _cell(amount, m, "right")
        + V
    )[:width]


def table_data_rows(
    width: int,
    cols: tuple[int, int, int, int],
    designation: str,
    qty: str,
    price: str,
    amount: str,
) -> list[str]:
    """Désignation longue : suite sur lignes suivantes (colonnes numériques vides)."""
    d = cols[0]
    name = (designation or "").strip()
    if len(name) <= d:
        return [table_data_row(width, cols, name, qty, price, amount)]
    rows = [table_data_row(width, cols, name[:d], qty, price, amount)]
    rest = name[d:]
    while rest:
        rows.append(table_data_row(width, cols, rest[:d], "", "", ""))
        rest = rest[d:]
    return rows


def total_underlined(width: int, amount: str) -> list[str]:
    """TOTAL + montant à droite, soulignement sous le montant uniquement."""
    from app.printers.ticket.layout import row

    amount = (amount or "").strip()
    line = row("TOTAL", amount, width)
    # Souligner uniquement la zone du montant (à droite).
    underline = (" " * (width - len(amount))) + ("─" * len(amount))
    return [line[:width], underline[:width]]


def frame_text(text: str, width: int, *, rounded: bool = True) -> list[str]:
    """Cadre du montant en lettres (coins arrondis = modèle photo)."""
    inner_w = max(4, width - 2)
    chunks: list[str] = []
    remaining = (text or "").strip() or "-"
    while remaining:
        chunks.append(remaining[:inner_w])
        remaining = remaining[inner_w:]
    if rounded:
        top, bot = RTL + (H * inner_w) + RTR, RBL + (H * inner_w) + RBR
    else:
        top, bot = TL + (H * inner_w) + TR, BL + (H * inner_w) + BR
    out = [top]
    for chunk in chunks:
        out.append(V + chunk.ljust(inner_w)[:inner_w] + V)
    out.append(bot)
    return [ln[:width] for ln in out]


# Alias rétrocompat
def hline(width: int, char: str = "-") -> str:
    return (char * width)[:width]


def open_header_row(width: int, cols: tuple[int, int, int, int]) -> str:
    return table_header_row(width, cols)


def open_data_row(width, cols, designation, qty, price, amount) -> str:
    return table_data_row(width, cols, designation, qty, price, amount)


def open_data_rows(width, cols, designation, qty, price, amount) -> list[str]:
    return table_data_rows(width, cols, designation, qty, price, amount)


def open_total_row(width, cols, amount) -> str:
    from app.printers.ticket.layout import row

    return row("TOTAL", amount, width)


def table_total_row(width, cols, amount) -> str:
    return open_total_row(width, cols, amount)


def table_total_top(width, cols) -> str:
    return table_mid(width, cols)


def table_total_bottom(width, cols) -> str:
    return table_bottom(width, cols)


def table_total_rule(width, cols) -> str:
    return table_bottom(width, cols)


def table_rule(width, cols) -> str:
    return table_mid(width, cols)
