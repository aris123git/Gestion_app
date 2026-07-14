"""Produits vendus par le commerce."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String
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

    purchase_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    sale_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    min_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    min_stock: Mapped[float] = mapped_column(Numeric(14, 3), default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped[Optional["Category"]] = relationship(  # noqa: F821
        back_populates="products"
    )
    unit: Mapped[Optional["Unit"]] = relationship()  # noqa: F821

    __table_args__ = (
        Index("ix_products_name_barcode", "name", "barcode"),
    )

    @property
    def is_low_stock(self) -> bool:
        return float(self.quantity) <= float(self.min_stock)

    @property
    def is_out_of_stock(self) -> bool:
        return float(self.quantity) <= 0

    @property
    def unit_name(self) -> str:
        return self.unit.name if self.unit else ""

    @property
    def category_name(self) -> str:
        return self.category.name if self.category else ""

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Product {self.name!r} qty={self.quantity}>"
