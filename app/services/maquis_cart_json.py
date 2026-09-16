"""Sérialisation panier Maquis (format compatible tablette CartJson)."""

from __future__ import annotations

from typing import List

from app.controllers.sale_controller import CartLine

_FIELD_SEP = "|"
_LINE_SEP = "\n"


def _sanitize(name: str) -> str:
    return name.replace(_FIELD_SEP, " ").replace(_LINE_SEP, " ").strip()


def encode_cart(lines: List[CartLine]) -> str:
    parts: List[str] = []
    for line in lines:
        if line.free_amount or line.loyalty_reward:
            continue
        if not line.product_id:
            continue
        parts.append(
            _FIELD_SEP.join(
                [
                    str(int(line.product_id)),
                    _sanitize(line.name or ""),
                    str(line.unit_price),
                    str(line.quantity),
                    "",
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
            purchase = float(fields[5]) if len(fields) > 5 and fields[5] else 0.0
            if quantity <= 0:
                continue
            out.append(
                CartLine(
                    product_id=pid,
                    name=name,
                    unit_price=unit_price,
                    quantity=quantity,
                    purchase_price=purchase,
                )
            )
    except (ValueError, TypeError):
        return []
    return out
