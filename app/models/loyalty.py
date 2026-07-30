"""Programme de fidélité clients (points)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class CustomerPoints(Base, TimestampMixin):
    """Solde de points de fidélité d'un client."""

    __tablename__ = "customer_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"), nullable=False, unique=True, index=True
    )
    points: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    lifetime_points: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    client: Mapped["Client"] = relationship()  # noqa: F821


class CustomerPointsHistory(Base):
    """Mouvement de points (gain, échange, ajustement)."""

    __tablename__ = "customer_points_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    delta: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    balance_after: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    reason: Mapped[str] = mapped_column(String(120), default="")
    sale_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sales.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
