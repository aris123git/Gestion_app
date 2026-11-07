"""Location de matériel : parc, contrats (départ, date de retour prévue), lignes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

RENTAL_OUT = "en_cours"
RENTAL_RETURNED = "rendu"
CONDITIONS = ["Bon état", "Usé", "À réparer", "Hors service"]


class RentalItem(Base, TimestampMixin):
    """Un type de matériel du parc (avec sa quantité)."""

    __tablename__ = "rental_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    category: Mapped[str] = mapped_column(String(80), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    rate_day: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    rate_week: Mapped[float] = mapped_column(Numeric(14, 3), default=0)     # 0 = jour × 7
    deposit: Mapped[float] = mapped_column(Numeric(14, 3), default=0)      # caution par unité
    condition: Mapped[str] = mapped_column(String(30), default="Bon état")
    service_every_days: Mapped[int] = mapped_column(Integer, default=0)    # révision tous les N jours de location (0 = non suivi)
    days_since_service: Mapped[int] = mapped_column(Integer, default=0)
    repair_cost: Mapped[float] = mapped_column(Numeric(14, 3), default=0)  # cumul des réparations
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Rental(Base, TimestampMixin):
    __tablename__ = "rentals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    client_label: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    id_document: Mapped[str] = mapped_column(String(120), default="")       # pièce d'identité remise
    start_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    due_date: Mapped[datetime] = mapped_column(DateTime)
    returned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=RENTAL_OUT, index=True)
    deposit: Mapped[float] = mapped_column(Numeric(14, 3), default=0)       # caution reçue
    paid: Mapped[float] = mapped_column(Numeric(14, 3), default=0)          # loyer encaissé
    late_fee: Mapped[float] = mapped_column(Numeric(14, 3), default=0)      # fixé au retour
    damage_fee: Mapped[float] = mapped_column(Numeric(14, 3), default=0)    # dégâts / pièces manquantes
    deposit_refunded: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    chantier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chantiers.id"), nullable=True)   # usage interne
    out_condition: Mapped[str] = mapped_column(Text, default="")
    return_condition: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    lines: Mapped[list["RentalLine"]] = relationship(back_populates="rental", cascade="all, delete-orphan")


class RentalLine(Base):
    __tablename__ = "rental_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rental_id: Mapped[int] = mapped_column(ForeignKey("rentals.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("rental_items.id"))
    label: Mapped[str] = mapped_column(String(160), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    rate_day: Mapped[float] = mapped_column(Numeric(14, 3), default=0)

    rental: Mapped[Rental] = relationship(back_populates="lines")
