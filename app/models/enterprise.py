"""Snapshots multi-magasins (Lot 1 : sync fichier JSON)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class EnterpriseSnapshot(Base, TimestampMixin):
    """Chiffres d'un magasin pour une journée (importés depuis le dossier partagé)."""

    __tablename__ = "enterprise_snapshots"
    __table_args__ = (
        UniqueConstraint("shop_id", "report_date", name="uq_enterprise_shop_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    shop_code: Mapped[str] = mapped_column(String(40), default="")
    shop_name: Mapped[str] = mapped_column(String(200), default="")
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(20), default="FCFA")
    cash_revenue: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    profit_gross: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    profit_net: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    expenses: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    sales_count: Mapped[int] = mapped_column(Integer, default=0)
    client_debts: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    client_debts_count: Mapped[int] = mapped_column(Integer, default=0)
    debt_repayments: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    treasury: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    source_path: Mapped[str] = mapped_column(String(500), default="")
    imported_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EnterpriseSnapshot {self.shop_code} {self.report_date}>"
