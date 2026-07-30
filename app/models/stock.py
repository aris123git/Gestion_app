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

# Motifs normalisés de perte / sortie (Sprint 4).
LOSS_REASON_BREAKAGE = "casse"
LOSS_REASON_THEFT = "vol"
LOSS_REASON_EXPIRY = "péremption"
LOSS_REASON_INTERNAL = "consommation interne"
LOSS_REASON_GIFT = "don"
LOSS_REASON_OTHER = "autre"

LOSS_REASONS = [
    LOSS_REASON_BREAKAGE,
    LOSS_REASON_THEFT,
    LOSS_REASON_EXPIRY,
    LOSS_REASON_INTERNAL,
    LOSS_REASON_GIFT,
    LOSS_REASON_OTHER,
]


class StockMovement(Base):
    """Trace un changement de quantité d'un produit (historique auditable)."""

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(30), default=MOVEMENT_IN)
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    quantity_before: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    quantity_after: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    invoice_number: Mapped[str] = mapped_column(String(80), default="")
    supplier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("suppliers.id"), nullable=True
    )
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    product: Mapped["Product"] = relationship()  # noqa: F821
    user: Mapped[Optional["User"]] = relationship()  # noqa: F821
    supplier: Mapped[Optional["Supplier"]] = relationship()  # noqa: F821

    @property
    def signed_quantity(self) -> float:
        """Variation réelle de stock (positive = entrée, négative = sortie)."""
        return float(self.quantity_after) - float(self.quantity_before)

    @property
    def user_label(self) -> str:
        if not self.user:
            return "—"
        return self.user.full_name or self.user.username

    @property
    def supplier_name(self) -> str:
        return self.supplier.name if self.supplier else ""

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<StockMovement {self.movement_type} {self.quantity}>"
