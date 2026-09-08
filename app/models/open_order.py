"""Commandes ouvertes (Maquis Caisse PC) — liées à une table."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

STATUS_OPEN = "ouverte"
STATUS_SERVED = "servie"
STATUS_PAID = "payée"
STATUS_CANCELLED = "annulée"


class OpenOrder(Base, TimestampMixin):
    __tablename__ = "open_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    table_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dining_tables.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), default=STATUS_OPEN, index=True)
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    opened_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    table: Mapped[Optional["DiningTable"]] = relationship(  # noqa: F821
        back_populates="orders"
    )
    items: Mapped[List["OpenOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OpenOrderItem(Base):
    __tablename__ = "open_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("open_orders.id"), nullable=False, index=True
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )
    product_name: Mapped[str] = mapped_column(String(200), default="")
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    order: Mapped["OpenOrder"] = relationship(back_populates="items")
