"""Conversion de montants entiers en lettres (français)."""

from __future__ import annotations

_UNITS = (
    "zéro",
    "un",
    "deux",
    "trois",
    "quatre",
    "cinq",
    "six",
    "sept",
    "huit",
    "neuf",
    "dix",
    "onze",
    "douze",
    "treize",
    "quatorze",
    "quinze",
    "seize",
    "dix-sept",
    "dix-huit",
    "dix-neuf",
)
_TENS = (
    "",
    "",
    "vingt",
    "trente",
    "quarante",
    "cinquante",
    "soixante",
    "soixante",
    "quatre-vingt",
    "quatre-vingt",
)


def _under_hundred(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    tens, unit = divmod(n, 10)
    if tens == 7 or tens == 9:
        # 70–79 → soixante-dix… ; 90–99 → quatre-vingt-dix…
        base = _TENS[tens]
        return f"{base}-{_UNITS[10 + unit]}" if unit else (
            "soixante-dix" if tens == 7 else "quatre-vingt-dix"
        )
    if tens == 8:
        if unit == 0:
            return "quatre-vingts"
        return f"quatre-vingt-{_UNITS[unit]}"
    if unit == 0:
        return _TENS[tens]
    if unit == 1 and tens in (2, 3, 4, 5, 6):
        return f"{_TENS[tens]} et un"
    return f"{_TENS[tens]}-{_UNITS[unit]}"


def _under_thousand(n: int) -> str:
    if n < 100:
        return _under_hundred(n)
    hundreds, rest = divmod(n, 100)
    if hundreds == 1:
        head = "cent"
    else:
        head = f"{_UNITS[hundreds]} cent"
        if rest == 0:
            head += "s"
    if rest == 0:
        return head
    return f"{head} {_under_hundred(rest)}"


def int_to_french_words(n: int) -> str:
    """Convertit un entier ≥ 0 en lettres françaises (jusqu'aux milliards)."""
    n = int(n)
    if n < 0:
        return f"moins {int_to_french_words(-n)}"
    if n < 1000:
        return _under_thousand(n)

    parts: list[str] = []
    billions, n = divmod(n, 1_000_000_000)
    millions, n = divmod(n, 1_000_000)
    thousands, n = divmod(n, 1000)

    if billions:
        if billions == 1:
            parts.append("un milliard")
        else:
            parts.append(f"{_under_thousand(billions)} milliards")
    if millions:
        if millions == 1:
            parts.append("un million")
        else:
            parts.append(f"{_under_thousand(millions)} millions")
    if thousands:
        if thousands == 1:
            parts.append("mille")
        else:
            parts.append(f"{_under_thousand(thousands)} mille")
    if n:
        parts.append(_under_thousand(n))
    return " ".join(parts) if parts else "zéro"


def amount_in_words(amount, currency: str = "F CFA") -> str:
    """Montant arrondi à l'unité, en toutes lettres + devise."""
    try:
        value = int(round(float(amount)))
    except (TypeError, ValueError):
        value = 0
    words = int_to_french_words(abs(value))
    cur = (currency or "F CFA").strip()
    # FCFA → F CFA pour lecture naturelle.
    if cur.upper() in ("FCFA", "F.CFA", "XOF"):
        cur = "F CFA"
    prefix = "moins " if value < 0 else ""
    return f"{prefix}{words} {cur}".strip()
