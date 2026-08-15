"""Contrôleur des produits (CRUD, recherche, alertes de stock)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.product import Product
from app.models.sale import SaleItem
from app.models.stock import MOVEMENT_CORRECTION, StockMovement
from app.utils.helpers import to_float


class ProductController:
    @staticmethod
    def _clean_barcode(value) -> str:
        return str(value or "").strip()

    @staticmethod
    def _ensure_unique_barcode(session, barcode: str, product_id: Optional[int] = None) -> None:
        if not barcode:
            return
        query = select(Product.id).where(Product.barcode == barcode)
        if product_id is not None:
            query = query.where(Product.id != product_id)
        if session.scalar(query):
            raise ValueError("Un produit existe déjà avec ce code-barres.")

    @staticmethod
    def _record_quantity_adjustment(
        session,
        product: Product,
        before: float,
        after: float,
        reason: str,
        user_id: Optional[int],
    ) -> None:
        if abs(after - before) < 0.001:
            return
        session.add(
            StockMovement(
                product_id=product.id,
                movement_type=MOVEMENT_CORRECTION,
                quantity=abs(after - before),
                quantity_before=before,
                quantity_after=after,
                unit_cost=float(product.purchase_price or 0),
                reason=reason,
                user_id=user_id,
            )
        )

    @staticmethod
    def list(
        search: str = "",
        category_id: Optional[int] = None,
        only_active: bool = True,
        limit: int = 5000,
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
            query = query.order_by(Product.name).limit(limit)
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
        barcode = ProductController._clean_barcode(barcode)
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
    def _validate_prices(data: dict) -> None:
        """Refuse tout prix négatif (achat / vente / minimum)."""
        for key, label in (
            ("purchase_price", "Le prix d'achat"),
            ("sale_price", "Le prix de vente"),
            ("min_price", "Le prix minimum"),
        ):
            if key in data and to_float(data.get(key)) < 0:
                raise ValueError(f"{label} ne peut pas être négatif.")

    @staticmethod
    def create(data: dict, user_id: Optional[int] = None) -> Product:
        barcode = ProductController._clean_barcode(data.get("barcode"))
        ProductController._validate_prices(data)
        quantity = to_float(data.get("quantity"))
        if quantity < 0:
            raise ValueError("La quantité en stock ne peut pas être négative.")
        with session_scope() as session:
            ProductController._ensure_unique_barcode(session, barcode)
            product = Product(
                name=str(data.get("name", "")).strip(),
                barcode=barcode,
                reference=str(data.get("reference", "")).strip(),
                category_id=data.get("category_id"),
                unit_id=data.get("unit_id"),
                purchase_price=to_float(data.get("purchase_price")),
                sale_price=to_float(data.get("sale_price")),
                min_price=to_float(data.get("min_price")),
                pack_content=to_float(data.get("pack_content")),
                quantity=quantity,
                min_stock=to_float(data.get("min_stock")),
                free_amount_sale=bool(data.get("free_amount_sale", False)),
                is_active=bool(data.get("is_active", True)),
            )
            session.add(product)
            session.flush()
            ProductController._record_quantity_adjustment(
                session,
                product,
                0.0,
                quantity,
                "Stock initial produit",
                user_id,
            )
            session.expunge(product)
            return product

    @staticmethod
    def update(
        product_id: int,
        data: dict,
        user_id: Optional[int] = None,
        username: str = "",
    ) -> None:
        from app.services.price_history_service import PriceHistoryService

        new_price = to_float(data.get("sale_price"))
        ProductController._validate_prices(data)
        price_changed = False
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return
            new_barcode = ProductController._clean_barcode(
                data.get("barcode", product.barcode)
            )
            new_quantity = to_float(data.get("quantity", product.quantity))
            if new_quantity < 0:
                raise ValueError("La quantité en stock ne peut pas être négative.")
            ProductController._ensure_unique_barcode(session, new_barcode, product_id)
            old_price = float(product.sale_price)
            old_quantity = float(product.quantity)
            product.name = str(data.get("name", product.name)).strip()
            product.barcode = new_barcode
            product.reference = str(data.get("reference", product.reference)).strip()
            product.category_id = data.get("category_id")
            product.unit_id = data.get("unit_id")
            product.purchase_price = to_float(data.get("purchase_price"))
            # Le prix de vente est mis à jour via PriceHistoryService si modifié.
            product.min_price = to_float(data.get("min_price"))
            product.pack_content = to_float(data.get("pack_content", product.pack_content))
            product.quantity = new_quantity
            product.min_stock = to_float(data.get("min_stock"))
            product.free_amount_sale = bool(
                data.get("free_amount_sale", product.free_amount_sale)
            )
            product.is_active = bool(data.get("is_active", True))
            ProductController._record_quantity_adjustment(
                session,
                product,
                old_quantity,
                new_quantity,
                "Ajustement fiche produit",
                user_id,
            )
            price_changed = abs(old_price - new_price) >= 0.001
            if not price_changed:
                product.sale_price = new_price
        if price_changed:
            PriceHistoryService.record_change(
                product_id,
                new_price,
                reason="Fiche produit",
                user_id=user_id,
                username=username,
                apply=True,
            )

    @staticmethod
    def update_price(
        product_id: int,
        new_price: float,
        reason: str = "Modification POS",
        user_id: Optional[int] = None,
        username: str = "",
    ) -> None:
        """Met à jour définitivement le prix de vente (avec historique)."""
        from app.services.price_history_service import PriceHistoryService

        PriceHistoryService.record_change(
            product_id,
            new_price,
            reason=reason,
            user_id=user_id,
            username=username,
            apply=True,
        )

    @staticmethod
    def delete(product_id: int) -> str:
        """Supprime si possible, sinon désactive pour préserver l'historique."""
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return "missing"
            sale_count = session.scalar(
                select(func.count()).select_from(SaleItem).where(
                    SaleItem.product_id == product_id
                )
            ) or 0
            if sale_count:
                product.is_active = False
                return "deactivated"
            session.delete(product)
            return "deleted"

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
