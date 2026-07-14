"""Contrôleur des catégories (CRUD + recherche)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.category import Category
from app.models.product import Product


class CategoryController:
    @staticmethod
    def list(search: str = "") -> List[Category]:
        with session_scope() as session:
            query = select(Category).order_by(Category.name)
            if search:
                query = query.where(Category.name.ilike(f"%{search}%"))
            rows = session.scalars(query).all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def get(category_id: int) -> Optional[Category]:
        with session_scope() as session:
            category = session.get(Category, category_id)
            if category:
                session.expunge(category)
            return category

    @staticmethod
    def create(name: str, description: str = "") -> Category:
        with session_scope() as session:
            category = Category(name=name.strip(), description=description.strip())
            session.add(category)
            session.flush()
            session.expunge(category)
            return category

    @staticmethod
    def update(category_id: int, name: str, description: str = "") -> None:
        with session_scope() as session:
            category = session.get(Category, category_id)
            if category:
                category.name = name.strip()
                category.description = description.strip()

    @staticmethod
    def delete(category_id: int) -> None:
        """Supprime une catégorie et détache ses produits (mise à NULL)."""
        with session_scope() as session:
            category = session.get(Category, category_id)
            if not category:
                return
            for product in session.scalars(
                select(Product).where(Product.category_id == category_id)
            ):
                product.category_id = None
            session.delete(category)

    @staticmethod
    def count() -> int:
        with session_scope() as session:
            return session.scalar(select(func.count()).select_from(Category)) or 0
