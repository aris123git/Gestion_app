"""Helpers de mise en page monospace (indépendants des designs)."""

from __future__ import annotations


def sep(char: str = "-", width: int = 32) -> str:
    return (char * width)[:width]


def row(left: str, right: str, width: int) -> str:
    """Place ``left`` à gauche et ``right`` à droite."""
    left = left or ""
    right = right or ""
    space = width - len(left) - len(right)
    if space < 1:
        left = left[: max(0, width - len(right) - 1)]
        space = max(1, width - len(left) - len(right))
    return f"{left}{' ' * space}{right}"


def center(text: str, width: int) -> str:
    return (text or "")[:width].center(width)


def wrap_text(text: str, width: int) -> list[str]:
    """Découpe un texte long en lignes de largeur max."""
    text = text or ""
    if not text:
        return []
    if width <= 0:
        return [text]
    lines: list[str] = []
    while text:
        lines.append(text[:width])
        text = text[width:]
    return lines


def fit_left_right(left: str, right: str, width: int) -> list[str]:
    """Une ligne left/right, ou deux si le nom est trop long."""
    left = (left or "").strip()
    right = (right or "").strip()
    max_left = max(4, width - len(right) - 1)
    if len(left) <= max_left:
        return [row(left, right, width)]
    out = wrap_text(left, width)
    if right:
        out.append(row("", right, width))
    return out
