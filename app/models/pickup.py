"""Enlèvements (bons d'enlèvement) : marchandise prise chez un fournisseur puis livrée aux clients.

Cycle : brouillon → envoyé (au fournisseur) → validé (signé, le stock entre par un achat)
→ clôturé (le reste non livré devient une perte, ex. évaporation).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

STATUS_DRAFT = "draft"
STATUS_SENT = "sent"
STATUS_VALIDATED = "validated"
STATUS_CLOSED = "closed"
STATUS_LABELS = {
    STATUS_DRAFT: "Brouillon",
    STATUS_SENT: "Envoyé",
    STATUS_VALIDATED: "Validé",
    STATUS_CLOSED: "Clôturé",
}


class Pickup(Base):
    __tablename__ = "pickups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"), nullable=True, index=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_DRAFT, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    driver: Mapped[str] = mapped_column(String(120), default="")      # information : chauffeur
    truck: Mapped[str] = mapped_column(String(60), default="")        # information : n° du camion
    reference: Mapped[str] = mapped_column(String(80), default="")    # information : référence (bon fournisseur…)
    signed_file: Mapped[str] = mapped_column(String(400), default="")
    purchase_id: Mapped[Optional[int]] = mapped_column(ForeignKey("purchases.id"), nullable=True)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    loss_reason: Mapped[str] = mapped_column(String(80), default="")
    loss_bearer: Mapped[str] = mapped_column(String(20), default="")  # "client" (facturée aux stations) ou "company"
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    supplier: Mapped[Optional["Supplier"]] = relationship()  # noqa: F821
    items: Mapped[List["PickupItem"]] = relationship(back_populates="pickup", cascade="all, delete-orphan", order_by="PickupItem.id")


class PickupItem(Base):
    __tablename__ = "pickup_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pickup_id: Mapped[int] = mapped_column(ForeignKey("pickups.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), default="")
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    line_total: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    loss_quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    billed_loss: Mapped[float] = mapped_column(Numeric(14, 3), default=0)  # part de la perte facturée aux clients

    pickup: Mapped[Pickup] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()  # noqa: F821
    deliveries: Mapped[List["PickupDelivery"]] = relationship(back_populates="item", cascade="all, delete-orphan")


class PickupDelivery(Base):
    """Quantité d'une ligne d'enlèvement livrée à un client (une vente = une station)."""

    __tablename__ = "pickup_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pickup_item_id: Mapped[int] = mapped_column(ForeignKey("pickup_items.id"), nullable=False, index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    item: Mapped[PickupItem] = relationship(back_populates="deliveries")
