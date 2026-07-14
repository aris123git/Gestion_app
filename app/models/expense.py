"""Dépenses du commerce."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class Expense(Base, TimestampMixin):
    """Sortie d'argent (loyer, salaire, transport, ...)."""

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(100), default="Autres")
    label: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Expense {self.category} {self.amount}>"
