"""Ventes, lignes de vente et paiements."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class Sale(Base, TimestampMixin):
    """Ticket de vente (en-tête)."""

    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id"), nullable=True
    )

    subtotal: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    discount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    amount_received: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    change_due: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    profit: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    status: Mapped[str] = mapped_column(String(20), default="completed")

    user: Mapped[Optional["User"]] = relationship()  # noqa: F821
    client: Mapped[Optional["Client"]] = relationship()  # noqa: F821
    items: Mapped[List["SaleItem"]] = relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )
    payments: Mapped[List["Payment"]] = relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )

    @property
    def cashier_name(self) -> str:
        return self.user.full_name or self.user.username if self.user else "—"

    @property
    def client_name(self) -> str:
        return self.client.name if self.client else "Client de passage"

    @property
    def payment_summary(self) -> str:
        return ", ".join(f"{p.method}: {float(p.amount):,.0f}" for p in self.payments)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Sale {self.ticket_number} total={self.total}>"


class SaleItem(Base):
    """Ligne d'un ticket : produit, quantité, prix."""

    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False)
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )

    product_name: Mapped[str] = mapped_column(String(200), default="")
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    purchase_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    sale: Mapped["Sale"] = relationship(back_populates="items")
    product: Mapped[Optional["Product"]] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<SaleItem {self.product_name} x{self.quantity}>"


class Payment(Base):
    """Paiement rattaché à une vente (permet le paiement mixte)."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False)
    method: Mapped[str] = mapped_column(String(50), default="Espèces")
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    sale: Mapped["Sale"] = relationship(back_populates="payments")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Payment {self.method} {self.amount}>"
