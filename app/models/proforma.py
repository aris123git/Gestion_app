"""Factures proforma : document commercial (sans mouvement de stock ni encaissement)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

STATUS_OPEN = "Ouverte"
STATUS_ACCEPTED = "Acceptée"
STATUS_REFUSED = "Refusée"
STATUS_INVOICED = "Facturée"
STATUSES = (STATUS_OPEN, STATUS_ACCEPTED, STATUS_REFUSED, STATUS_INVOICED)


class Proforma(Base, TimestampMixin):
    __tablename__ = "proformas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)      # ex. 062/2026
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_OPEN)
    client_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    client_name: Mapped[str] = mapped_column(String(200), default="")
    client_phone: Mapped[str] = mapped_column(String(120), default="")
    client_email: Mapped[str] = mapped_column(String(150), default="")
    client_ifu: Mapped[str] = mapped_column(String(80), default="")
    client_rccm: Mapped[str] = mapped_column(String(120), default="")
    client_regime: Mapped[str] = mapped_column(String(80), default="")
    client_division: Mapped[str] = mapped_column(String(120), default="")
    client_address: Mapped[str] = mapped_column(String(300), default="")
    subject: Mapped[str] = mapped_column(String(300), default="")
    tax_label: Mapped[str] = mapped_column(String(40), default="")
    tax_rate: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    responsible: Mapped[str] = mapped_column(String(150), default="")
    responsible_phone: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    sale_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)     # vente créée à partir de cette proforma

    lines: Mapped[List["ProformaLine"]] = relationship(
        back_populates="proforma", cascade="all, delete-orphan", order_by="ProformaLine.position", lazy="selectin"
    )


class ProformaLine(Base):
    __tablename__ = "proforma_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proforma_id: Mapped[int] = mapped_column(ForeignKey("proformas.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(300))
    packaging: Mapped[str] = mapped_column(String(40), default="")      # CDT : B/100, Sachet…
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=1)
    unit: Mapped[str] = mapped_column(String(30), default="")           # kg, carton…
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    proforma: Mapped[Proforma] = relationship(back_populates="lines")

    @property
    def total(self) -> float:
        return round(float(self.quantity or 0) * float(self.unit_price or 0), 2)
