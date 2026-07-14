"""Catégories de produits."""

from __future__ import annotations

from typing import List

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class Category(Base, TimestampMixin):
    """Catégorie regroupant des produits."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    products: Mapped[List["Product"]] = relationship(  # noqa: F821
        back_populates="category"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Category {self.name!r}>"
