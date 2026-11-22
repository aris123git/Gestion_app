"""Produits vendus par le commerce."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class Product(Base, TimestampMixin):
    """Article du catalogue avec prix, stock et unité."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    barcode: Mapped[str] = mapped_column(String(80), default="", index=True)
    reference: Mapped[str] = mapped_column(String(80), default="", index=True)

    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )
    unit_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("units.id"), nullable=True
    )
    supplier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("suppliers.id"), nullable=True
    )

    purchase_price: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    sale_price: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    min_price: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    # Taxe (%) INCLUSE dans le prix de vente (prix saisi = TTC). 0 = aucune taxe.
    tax_rate: Mapped[float] = mapped_column(Numeric(6, 3), default=0)

    quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    min_stock: Mapped[float] = mapped_column(Numeric(14, 3), default=0)

    # Vente au montant libre (ex. poissonnerie : client demande « 300 F »).
    # - purchase_price = prix d'achat par unité de stock (carton)
    # - pack_content = contenu estimatif (kg / carton)
    # - sale_price = prix de vente de référence (F / kg) pour marge estimée
    # Vente sans stock : le produit n'est pas suivi en stock (jamais de rupture,
    # aucune sortie/entrée de stock à la vente ni à l'annulation).
    sell_without_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    free_amount_sale: Mapped[bool] = mapped_column(Boolean, default=False)
    pack_content: Mapped[float] = mapped_column(Numeric(14, 3), default=0)

    # Chemin local de l'image produit (dossier DATA_DIR/product_images).
    image_path: Mapped[str] = mapped_column(String(500), default="")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Accessoires rapides (Maquis) : pour composer un plat de base en un clic
    # (ex. Poisson braisé + attiéké 300 + alloco 200 + frites 500), sans passer
    # par la vente au montant libre. Stocké en JSON : [{"name": ..., "price": ...}].
    # Pas de stock propre sur les accessoires : seul le produit de base en a un.
    accessories_json: Mapped[str] = mapped_column(Text, default="")

    category: Mapped[Optional["Category"]] = relationship(  # noqa: F821
        back_populates="products"
    )
    unit: Mapped[Optional["Unit"]] = relationship()  # noqa: F821

    __table_args__ = (
        Index("ix_products_name_barcode", "name", "barcode"),
    )

    @property
    def accessories(self) -> list[dict]:
        """Accessoires rapides configurés sur ce produit : [{"name": str, "price": float}]."""
        if not self.accessories_json:
            return []
        try:
            data = json.loads(self.accessories_json)
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if isinstance(item, dict) and str(item.get("name") or "").strip():
                try:
                    price = float(item.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0.0
                out.append({"name": str(item["name"]).strip(), "price": price})
        return out

    def set_accessories(self, items: list[dict]) -> None:
        clean = []
        for item in items or []:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            try:
                price = float(item.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            clean.append({"name": name, "price": price})
        self.accessories_json = json.dumps(clean, ensure_ascii=False)

    @property
    def is_low_stock(self) -> bool:
        if self.sell_without_stock:
            return False
        return float(self.quantity) <= float(self.min_stock)

    @property
    def is_out_of_stock(self) -> bool:
        if self.sell_without_stock:
            return False
        return float(self.quantity) <= 0

    @property
    def cost_per_sale_unit(self) -> float:
        """Coût d'achat estimé par unité de vente (ex. F/kg)."""
        content = float(self.pack_content or 0)
        if content <= 0:
            return float(self.purchase_price or 0)
        return float(self.purchase_price or 0) / content

    @property
    def unit_name(self) -> str:
        return self.unit.name if self.unit else ""

    @property
    def category_name(self) -> str:
        return self.category.name if self.category else ""

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Product {self.name!r} qty={self.quantity}>"
