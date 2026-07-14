"""Clients du commerce (avec gestion des dettes)."""

from __future__ import annotations

from sqlalchemy import Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class Client(Base, TimestampMixin):
    """Client identifié, avec un solde de dette éventuel."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(80), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    email: Mapped[str] = mapped_column(String(150), default="")
    debt: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    notes: Mapped[str] = mapped_column(Text, default="")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Client {self.name!r} debt={self.debt}>"
