"""Contrôleur des produits (CRUD, recherche, alertes de stock)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.product import Product
from app.utils.helpers import to_float


class ProductController:
    @staticmethod
    def list(
        search: str = "",
        category_id: Optional[int] = None,
        only_active: bool = True,
    ) -> List[Product]:
        """Liste les produits, avec recherche instantanée et filtre catégorie."""
        with session_scope() as session:
            query = select(Product).options(
                joinedload(Product.category), joinedload(Product.unit)
            )
            if only_active:
                query = query.where(Product.is_active.is_(True))
            if category_id:
                query = query.where(Product.category_id == category_id)
            if search:
                pattern = f"%{search}%"
                query = query.where(
                    or_(
                        Product.name.ilike(pattern),
                        Product.barcode.ilike(pattern),
                        Product.reference.ilike(pattern),
                    )
                )
            query = query.order_by(Product.name).limit(1000)
            rows = session.scalars(query).unique().all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def get(product_id: int) -> Optional[Product]:
        with session_scope() as session:
            product = session.scalar(
                select(Product)
                .options(joinedload(Product.category), joinedload(Product.unit))
                .where(Product.id == product_id)
            )
            if product:
                session.expunge(product)
            return product

    @staticmethod
    def find_by_barcode(barcode: str) -> Optional[Product]:
        barcode = barcode.strip()
        if not barcode:
            return None
        with session_scope() as session:
            product = session.scalar(
                select(Product)
                .options(joinedload(Product.category), joinedload(Product.unit))
                .where(Product.barcode == barcode, Product.is_active.is_(True))
            )
            if product:
                session.expunge(product)
            return product

    @staticmethod
    def create(data: dict) -> Product:
        with session_scope() as session:
            product = Product(
                name=str(data.get("name", "")).strip(),
                barcode=str(data.get("barcode", "")).strip(),
                reference=str(data.get("reference", "")).strip(),
                category_id=data.get("category_id"),
                unit_id=data.get("unit_id"),
                purchase_price=to_float(data.get("purchase_price")),
                sale_price=to_float(data.get("sale_price")),
                min_price=to_float(data.get("min_price")),
                quantity=to_float(data.get("quantity")),
                min_stock=to_float(data.get("min_stock")),
                is_active=bool(data.get("is_active", True)),
            )
            session.add(product)
            session.flush()
            session.expunge(product)
            return product

    @staticmethod
    def update(product_id: int, data: dict) -> None:
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return
            product.name = str(data.get("name", product.name)).strip()
            product.barcode = str(data.get("barcode", product.barcode)).strip()
            product.reference = str(data.get("reference", product.reference)).strip()
            product.category_id = data.get("category_id")
            product.unit_id = data.get("unit_id")
            product.purchase_price = to_float(data.get("purchase_price"))
            product.sale_price = to_float(data.get("sale_price"))
            product.min_price = to_float(data.get("min_price"))
            product.quantity = to_float(data.get("quantity"))
            product.min_stock = to_float(data.get("min_stock"))
            product.is_active = bool(data.get("is_active", True))

    @staticmethod
    def update_price(product_id: int, new_price: float) -> None:
        """Met à jour définitivement le prix de vente d'un produit (POS)."""
        with session_scope() as session:
            product = session.get(Product, product_id)
            if product:
                product.sale_price = to_float(new_price)

    @staticmethod
    def delete(product_id: int) -> None:
        with session_scope() as session:
            product = session.get(Product, product_id)
            if product:
                session.delete(product)

    @staticmethod
    def count() -> int:
        with session_scope() as session:
            return session.scalar(select(func.count()).select_from(Product)) or 0

    @staticmethod
    def low_stock(limit: int = 100) -> List[Product]:
        with session_scope() as session:
            rows = session.scalars(
                select(Product)
                .options(joinedload(Product.unit))
                .where(
                    Product.is_active.is_(True),
                    Product.quantity <= Product.min_stock,
                )
                .order_by(Product.quantity)
                .limit(limit)
            ).unique().all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def out_of_stock(limit: int = 100) -> List[Product]:
        with session_scope() as session:
            rows = session.scalars(
                select(Product)
                .options(joinedload(Product.unit))
                .where(Product.is_active.is_(True), Product.quantity <= 0)
                .order_by(Product.name)
                .limit(limit)
            ).unique().all()
            session.expunge_all()
            return list(rows)
