"""Mouvements de stock (entrées, sorties, inventaire, corrections)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

# Types de mouvements normalisés.
MOVEMENT_IN = "entrée"
MOVEMENT_OUT = "sortie"
MOVEMENT_INVENTORY = "inventaire"
MOVEMENT_CORRECTION = "correction"
MOVEMENT_SALE = "vente"


class StockMovement(Base):
    """Trace un changement de quantité d'un produit."""

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(30), default=MOVEMENT_IN)
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    quantity_before: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    quantity_after: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    product: Mapped["Product"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<StockMovement {self.movement_type} {self.quantity}>"
