"""Fournisseurs du commerce."""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class Supplier(Base, TimestampMixin):
    """Fournisseur avec ses coordonnées."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(80), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    email: Mapped[str] = mapped_column(String(150), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Supplier {self.name!r}>"
