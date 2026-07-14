"""Initialisation des données par défaut (unités, catégories, admin).

Idempotent : peut être appelé à chaque démarrage sans dupliquer les données.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app import config
from app.database.connection import session_scope
from app.models.category import Category
from app.models.settings import ShopInfo
from app.models.unit import Unit
from app.models.user import User
from app.utils.security import hash_password

DEFAULT_CATEGORIES = ["Général", "Boissons", "Alimentation", "Divers"]


def seed_units() -> None:
    with session_scope() as session:
        existing = {u.name for u in session.scalars(select(Unit)).all()}
        for name in config.DEFAULT_UNITS:
            if name not in existing:
                session.add(Unit(name=name, is_default=True))


def seed_categories() -> None:
    with session_scope() as session:
        existing = {c.name for c in session.scalars(select(Category)).all()}
        for name in DEFAULT_CATEGORIES:
            if name not in existing:
                session.add(Category(name=name))


def seed_admin() -> bool:
    """Crée un compte administrateur par défaut si aucun utilisateur n'existe.

    Retourne ``True`` si l'admin par défaut a été créé (identifiants
    ``admin`` / ``admin``), afin que l'interface puisse inviter à le sécuriser.
    """
    with session_scope() as session:
        count = session.scalar(select(func.count()).select_from(User)) or 0
        if count == 0:
            session.add(
                User(
                    username="admin",
                    full_name="Administrateur",
                    password_hash=hash_password("admin"),
                    role="Administrateur",
                    is_active=True,
                )
            )
            return True
    return False


def seed_shop_info() -> None:
    with session_scope() as session:
        shop = session.get(ShopInfo, 1)
        if not shop:
            session.add(ShopInfo(id=1))


def seed_all() -> bool:
    """Exécute toutes les initialisations. Retourne True si admin par défaut créé."""
    seed_shop_info()
    seed_units()
    seed_categories()
    return seed_admin()
