"""Helpers de tableau pour tickets thermiques (facture modèle exact).

Deux styles :
- ouvert (lignes horizontales sous en-tête / sous articles) — modèle facture ;
- encadré (box-drawing) — cadre du montant en lettres uniquement.
"""

from __future__ import annotations

# Traits continus (cadre montant en lettres).
H, V = "─", "│"
TL, TR, BL, BR = "┌", "┐", "└", "┘"
T, B, LJ, RJ, X = "┬", "┴", "├", "┤", "┼"

# Coins arrondis (legacy / optionnel).
RTL, RTR, RBL, RBR = "╭", "╮", "╰", "╯"


def table_column_widths(width: int) -> tuple[int, int, int, int]:
    """Largeurs Designation / Qte / Prix / Montant (espaces inclus hors gaps)."""
    # 3 séparateurs d'1 espace min entre 4 colonnes.
    gaps = 3
    usable = max(16, width - gaps)
    if width <= 32:
        qte, prix, montant = 3, 6, 7
    else:
        qte, prix, montant = 4, 8, 10
    des = max(6, usable - qte - prix - montant)
    while des + qte + prix + montant + gaps > width and des > 6:
        des -= 1
    while des + qte + prix + montant + gaps > width and montant > 5:
        montant -= 1
    return des, qte, prix, montant


def _cell(text: str, width: int, align: str = "left") -> str:
    text = (text or "")[:width]
    if align == "right":
        return text.rjust(width)
    if align == "center":
        return text.center(width)
    return text.ljust(width)


def _compose_open(
    cols: tuple[int, int, int, int],
    designation: str,
    qty: str,
    price: str,
    amount: str,
    *,
    width: int,
) -> str:
    """Ligne ouverte : Designation (gauche) + Qte/Prix/Montant (droite)."""
    d, q, p, m = cols
    gap = " "
    body = (
        _cell(designation, d)
        + gap
        + _cell(qty, q, "right")
        + gap
        + _cell(price, p, "right")
        + gap
        + _cell(amount, m, "right")
    )
    return body[:width].ljust(min(width, len(body)))[:width]


def open_header_row(width: int, cols: tuple[int, int, int, int]) -> str:
    if width <= 32:
        labels = ("Article", "Qte", "Prix", "Montant")
    else:
        labels = ("Désignation", "Qte", "Prix", "Montant")
    return _compose_open(cols, labels[0], labels[1], labels[2], labels[3], width=width)


def open_data_row(
    width: int,
    cols: tuple[int, int, int, int],
    designation: str,
    qty: str,
    price: str,
    amount: str,
) -> str:
    return _compose_open(cols, designation, qty, price, amount, width=width)


def open_data_rows(
    width: int,
    cols: tuple[int, int, int, int],
    designation: str,
    qty: str,
    price: str,
    amount: str,
) -> list[str]:
    """Lignes article : désignation longue → suite sans casser les colonnes."""
    d = cols[0]
    name = (designation or "").strip()
    if len(name) <= d:
        return [open_data_row(width, cols, name, qty, price, amount)]
    rows = [open_data_row(width, cols, name[:d], qty, price, amount)]
    rest = name[d:]
    while rest:
        rows.append(open_data_row(width, cols, rest[:d], "", "", ""))
        rest = rest[d:]
    return rows


def open_total_row(width: int, cols: tuple[int, int, int, int], amount: str) -> str:
    """TOTAL à gauche, montant à droite (pas de cadre)."""
    from app.printers.ticket.layout import row

    return row("TOTAL", amount, width)


def hline(width: int, char: str = "-") -> str:
    return (char * width)[:width]


# --- Cadre montant en lettres -------------------------------------------------


def frame_text(text: str, width: int, *, rounded: bool = False) -> list[str]:
    """Encadre un texte (montant en lettres). Coins droits par défaut (modèle)."""
    inner_w = max(4, width - 2)
    chunks: list[str] = []
    remaining = (text or "").strip()
    if not remaining:
        remaining = "-"
    while remaining:
        chunks.append(remaining[:inner_w])
        remaining = remaining[inner_w:]
    if rounded:
        top = RTL + (H * inner_w) + RTR
        bot = RBL + (H * inner_w) + RBR
    else:
        top = TL + (H * inner_w) + TR
        bot = BL + (H * inner_w) + BR
    lines = [top]
    for chunk in chunks:
        lines.append(V + chunk.ljust(inner_w)[:inner_w] + V)
    lines.append(bot)
    return [ln[:width] for ln in lines]


# --- Anciens helpers encadrés (rétrocompat tests / autres) --------------------


def _rule(cols: tuple[int, int, int, int], left: str, mid: str, right: str) -> str:
    d, q, p, m = cols
    return left + (H * d) + mid + (H * q) + mid + (H * p) + mid + (H * m) + right


def table_top(width: int, cols: tuple[int, int, int, int]) -> str:
    return _rule(cols, TL, T, TR)[:width]


def table_mid(width: int, cols: tuple[int, int, int, int]) -> str:
    return _rule(cols, LJ, X, RJ)[:width]


def table_bottom(width: int, cols: tuple[int, int, int, int]) -> str:
    return _rule(cols, BL, B, BR)[:width]


def table_rule(width: int, cols: tuple[int, int, int, int]) -> str:
    return table_mid(width, cols)


def table_header_row(width: int, cols: tuple[int, int, int, int]) -> str:
    return open_header_row(width, cols)


def table_data_row(
    width: int,
    cols: tuple[int, int, int, int],
    designation: str,
    qty: str,
    price: str,
    amount: str,
) -> str:
    return open_data_row(width, cols, designation, qty, price, amount)


def table_total_row(width: int, cols: tuple[int, int, int, int], amount: str) -> str:
    return open_total_row(width, cols, amount)


def table_total_top(width: int, cols: tuple[int, int, int, int]) -> str:
    return hline(width)


def table_total_bottom(width: int, cols: tuple[int, int, int, int]) -> str:
    return hline(width)


def table_total_rule(width: int, cols: tuple[int, int, int, int]) -> str:
    return hline(width)
