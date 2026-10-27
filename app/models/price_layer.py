"""Prix en attente : s'appliquent quand l'ancien stock est écoulé (méthode FIFO)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class PriceLayer(Base):
    """Lot arrivé (ou changement de prix programmé) avec ses propres prix.

    ``remaining`` = unités de ce lot encore en stock (0 pour un simple
    changement de prix programmé sans nouvelles unités).
    """

    __tablename__ = "product_price_layers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    remaining: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    purchase_price: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    sale_price: Mapped[Optional[float]] = mapped_column(Numeric(14, 3), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
