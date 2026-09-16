"""Paiements liés à une commande ouverte (comme order_payments sur tablette)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class OpenOrderPayment(Base):
    __tablename__ = "open_order_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("open_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_mode: Mapped[str] = mapped_column(String(40), default="Espèces")
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    amount_tendered: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    change_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_name: Mapped[str] = mapped_column(String(150), default="")

    order: Mapped["OpenOrder"] = relationship(back_populates="payments")  # noqa: F821
