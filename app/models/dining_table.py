"""Tables de salle (Maquis Caisse PC)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

STATUS_FREE = "libre"
STATUS_OCCUPIED = "occupée"
STATUS_RESERVED = "réservée"
STATUS_CLEANING = "à_nettoyer"


class DiningTable(Base, TimestampMixin):
    __tablename__ = "dining_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(40), default="")
    name: Mapped[str] = mapped_column(String(120), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=4)
    status: Mapped[str] = mapped_column(String(40), default=STATUS_FREE, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    orders: Mapped[List["OpenOrder"]] = relationship(  # noqa: F821
        back_populates="table"
    )

    @property
    def display_name(self) -> str:
        if self.name.strip():
            return self.name.strip()
        return f"Table {self.number or self.id}"
