"""Sérialisation panier Maquis (format compatible tablette CartJson)."""

from __future__ import annotations

from typing import List

from app.controllers.sale_controller import CartLine

_FIELD_SEP = "|"
_LINE_SEP = "\n"


def _sanitize(name: str) -> str:
    return name.replace(_FIELD_SEP, " ").replace(_LINE_SEP, " ").strip()


def encode_cart(lines: List[CartLine]) -> str:
    """Encode aussi montant libre (flag free=1) ; ignore offerts fidélité."""
    parts: List[str] = []
    for line in lines:
        if line.loyalty_reward:
            continue
        if not line.product_id and not line.free_amount:
            continue
        free_flag = "1" if line.free_amount else "0"
        pid = int(line.product_id or 0)
        parts.append(
            _FIELD_SEP.join(
                [
                    str(pid),
                    _sanitize(line.name or ""),
                    str(line.unit_price),
                    str(line.quantity),
                    free_flag,
                    str(line.purchase_price or 0),
                ]
            )
        )
    return _LINE_SEP.join(parts)


def decode_cart(raw: str | None) -> List[CartLine]:
    if not raw or not str(raw).strip():
        return []
    out: List[CartLine] = []
    try:
        for line in str(raw).split(_LINE_SEP):
            if not line.strip():
                continue
            fields = line.split(_FIELD_SEP)
            if len(fields) < 4:
                continue
            pid = int(fields[0])
            name = fields[1]
            unit_price = float(fields[2])
            quantity = float(fields[3])
            free_flag = fields[4] if len(fields) > 4 else ""
            purchase = float(fields[5]) if len(fields) > 5 and fields[5] else 0.0
            if quantity <= 0:
                continue
            free_amount = free_flag == "1"
            if not pid and not free_amount:
                continue
            out.append(
                CartLine(
                    product_id=pid or None,
                    name=name,
                    unit_price=unit_price,
                    quantity=quantity,
                    purchase_price=purchase,
                    free_amount=free_amount,
                )
            )
    except (ValueError, TypeError):
        return []
    return out
