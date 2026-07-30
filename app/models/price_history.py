"""Historique des modifications de prix de vente."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class PriceHistory(Base):
    """Trace chaque changement de prix (et marge associée)."""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    old_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    new_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    old_margin: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    new_margin: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")

    product: Mapped["Product"] = relationship()  # noqa: F821
    user: Mapped[Optional["User"]] = relationship()  # noqa: F821
