"""Écritures comptables manuelles (opérations diverses : capital, stock initial…)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class ManualEntry(Base, TimestampMixin):
    """Écriture simple en partie double : un compte débité, un compte crédité."""

    __tablename__ = "accounting_manual_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    debit_account: Mapped[str] = mapped_column(String(10), nullable=False)
    credit_account: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
