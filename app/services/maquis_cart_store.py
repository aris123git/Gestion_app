"""Persistance du panier caisse Maquis entre navigations (équivalent SavedStateHandle)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from app import config
from app.controllers.sale_controller import CartLine
from app.services import product_profile
from app.services.maquis_cart_json import decode_cart, encode_cart

_CART_DIR = config.DATA_DIR / "maquis_caisse"


def _cart_path(user_id: Optional[int]) -> Path:
    _CART_DIR.mkdir(parents=True, exist_ok=True)
    key = int(user_id) if user_id else 0
    return _CART_DIR / f"cart_user_{key}.txt"


def load_cart(user_id: Optional[int]) -> List[CartLine]:
    if not product_profile.is_maquis():
        return []
    path = _cart_path(user_id)
    if not path.is_file():
        return []
    try:
        return decode_cart(path.read_text(encoding="utf-8"))
    except OSError:
        return []


def save_cart(lines: List[CartLine], user_id: Optional[int]) -> None:
    if not product_profile.is_maquis():
        return
    path = _cart_path(user_id)
    try:
        text = encode_cart(lines)
        if text:
            path.write_text(text, encoding="utf-8")
        elif path.is_file():
            path.unlink()
    except OSError:
        pass


def clear_cart(user_id: Optional[int]) -> None:
    save_cart([], user_id)
