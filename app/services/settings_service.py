"""Service de gestion des informations du commerce et des préférences."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from app.database.connection import session_scope
from app.models.settings import Setting, ShopInfo


def get_shop_info() -> ShopInfo:
    """Retourne la fiche commerce (la crée avec des valeurs par défaut si absente)."""
    with session_scope() as session:
        shop = session.get(ShopInfo, 1)
        if not shop:
            shop = ShopInfo(id=1)
            session.add(shop)
            session.flush()
        session.expunge(shop)
        return shop


def save_shop_info(**fields) -> ShopInfo:
    """Met à jour la fiche commerce avec les champs fournis."""
    with session_scope() as session:
        shop = session.get(ShopInfo, 1)
        if not shop:
            shop = ShopInfo(id=1)
            session.add(shop)
        for key, value in fields.items():
            if hasattr(shop, key) and value is not None:
                setattr(shop, key, value)
        session.flush()
        session.expunge(shop)
        return shop


def is_configured() -> bool:
    """Indique si le premier démarrage a été effectué."""
    with session_scope() as session:
        shop = session.get(ShopInfo, 1)
        return bool(shop and shop.is_configured)


def get_setting(key: str, default: str = "") -> str:
    with session_scope() as session:
        setting = session.get(Setting, key)
        return setting.value if setting else default


def set_setting(key: str, value: str) -> None:
    with session_scope() as session:
        setting = session.get(Setting, key)
        if setting:
            setting.value = value
        else:
            session.add(Setting(key=key, value=value))


def get_currency() -> str:
    return get_shop_info().currency or "FCFA"
