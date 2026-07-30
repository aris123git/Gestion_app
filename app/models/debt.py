"""Dettes clients : créances et remboursements (source de vérité métier)."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

# Statuts normalisés d'une dette client.
STATUS_OPEN = "en_cours"
STATUS_PARTIAL = "partiellement_payée"
STATUS_PAID = "soldée"
STATUS_CANCELLED = "annulée"

ACTIVE_DEBT_STATUSES = (STATUS_OPEN, STATUS_PARTIAL)


class Debt(Base, TimestampMixin):
    """Créance client (liée éventuellement à une vente à crédit)."""

    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    sale_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales.id"), nullable=True, index=True
    )
    amount_initial: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    amount_remaining: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default=STATUS_OPEN, index=True)
    note: Mapped[str] = mapped_column(Text, default="")

    client: Mapped["Client"] = relationship()  # noqa: F821
    sale: Mapped[Optional["Sale"]] = relationship()  # noqa: F821
    payments: Mapped[List["DebtPayment"]] = relationship(
        back_populates="debt", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_DEBT_STATUSES

    @property
    def is_overdue(self) -> bool:
        if not self.is_active or not self.due_date:
            return False
        return self.due_date < date.today() and float(self.amount_remaining) > 0

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Debt {self.id} client={self.client_id} rem={self.amount_remaining}>"


class DebtPayment(Base):
    """Remboursement (partiel ou total) d'une dette client."""

    __tablename__ = "debt_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey("debts.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    payment_method: Mapped[str] = mapped_column(String(50), default="Espèces")
    payment_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, default="")

    debt: Mapped[Debt] = relationship(back_populates="payments")
    user: Mapped[Optional["User"]] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DebtPayment {self.id} debt={self.debt_id} amount={self.amount}>"
