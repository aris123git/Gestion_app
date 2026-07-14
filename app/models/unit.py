"""Unités de mesure des produits (kg, pièce, carton, ...)."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class Unit(Base):
    """Unité de vente/stock, prédéfinie ou créée par le commerçant."""

    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Unit {self.name!r}>"
