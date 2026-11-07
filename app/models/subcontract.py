"""Sous-traitance : sous-traitants, contrats par chantier (forfait + retenue), paiements (acomptes, situations, solde)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

SUB_RUNNING = "en_cours"
SUB_DONE = "termine"
SUB_CANCELLED = "annule"
SUB_STATUS_LABELS = {SUB_RUNNING: "En cours", SUB_DONE: "Terminé / réceptionné", SUB_CANCELLED: "Annulé"}
SUB_PAYMENT_KINDS = ["Acompte", "Situation", "Solde", "Libération de retenue"]
RETENTION_RELEASE = "Libération de retenue"


class Subcontractor(Base, TimestampMixin):
    __tablename__ = "subcontractors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    trade: Mapped[str] = mapped_column(String(80), default="")        # électricien, plombier, carreleur…
    phone: Mapped[str] = mapped_column(String(60), default="")
    address: Mapped[str] = mapped_column(String(200), default="")
    tax_id: Mapped[str] = mapped_column(String(60), default="")       # IFU / RCCM
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Subcontract(Base, TimestampMixin):
    __tablename__ = "subcontracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    chantier_id: Mapped[int] = mapped_column(ForeignKey("chantiers.id"), index=True)
    subcontractor_id: Mapped[int] = mapped_column(ForeignKey("subcontractors.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))                   # lot / tâche confiée
    amount: Mapped[float] = mapped_column(Numeric(14, 3), default=0)  # montant du forfait
    retention_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_planned: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=SUB_RUNNING, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    payments: Mapped[list["SubcontractPayment"]] = relationship(back_populates="subcontract", cascade="all, delete-orphan")


class SubcontractPayment(Base, TimestampMixin):
    __tablename__ = "subcontract_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subcontract_id: Mapped[int] = mapped_column(ForeignKey("subcontracts.id"), index=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    kind: Mapped[str] = mapped_column(String(40), default="Acompte")
    amount: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    reference: Mapped[str] = mapped_column(String(120), default="")
    expense_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # dépense créée sur le chantier
    notes: Mapped[str] = mapped_column(Text, default="")

    subcontract: Mapped[Subcontract] = relationship(back_populates="payments")
