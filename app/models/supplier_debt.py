"""Dettes fournisseurs (même logique métier que les dettes clients)."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.debt import (
    ACTIVE_DEBT_STATUSES,
    STATUS_CANCELLED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_PARTIAL,
)
from app.models.mixins import TimestampMixin


class SupplierDebt(Base, TimestampMixin):
    """Dette envers un fournisseur (liée éventuellement à un achat)."""

    __tablename__ = "supplier_debts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    purchase_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("purchases.id"), nullable=True, index=True
    )
    amount_initial: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    amount_remaining: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default=STATUS_OPEN, index=True)
    note: Mapped[str] = mapped_column(Text, default="")

    supplier: Mapped["Supplier"] = relationship()  # noqa: F821
    purchase: Mapped[Optional["Purchase"]] = relationship()  # noqa: F821
    payments: Mapped[List["SupplierDebtPayment"]] = relationship(
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


class SupplierDebtPayment(Base):
    """Remboursement d'une dette fournisseur."""

    __tablename__ = "supplier_debt_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    debt_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_debts.id"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    payment_method: Mapped[str] = mapped_column(String(50), default="Espèces")
    payment_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, index=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, default="")

    debt: Mapped[SupplierDebt] = relationship(back_populates="payments")
