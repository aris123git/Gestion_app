"""Avoirs clients (crédit magasin / bon d'achat) — Gestion App + Maquis Caisse."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

TYPE_CASH = "CASH"
TYPE_PRODUCT = "PRODUCT"

STATUS_ACTIVE = "actif"
STATUS_PARTIAL = "partiellement_utilisé"
STATUS_USED = "soldé"
STATUS_EXPIRED = "expiré"
STATUS_CANCELLED = "annulé"

ACTIVE_AVOIR_STATUSES = (STATUS_ACTIVE, STATUS_PARTIAL)


class Avoir(Base, TimestampMixin):
    """Bon d'avoir utilisable comme paiement (montant ou produit)."""

    __tablename__ = "avoirs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id"), nullable=True, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    avoir_type: Mapped[str] = mapped_column(String(20), default=TYPE_CASH)
    amount_initial: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    amount_remaining: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )
    product_qty: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    expires_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default=STATUS_ACTIVE, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    sale_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales.id"), nullable=True
    )

    client: Mapped[Optional["Client"]] = relationship()  # noqa: F821
    product: Mapped[Optional["Product"]] = relationship()  # noqa: F821
    redemptions: Mapped[List["AvoirRedemption"]] = relationship(
        back_populates="avoir", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_AVOIR_STATUSES


class AvoirRedemption(Base):
    """Utilisation partielle ou totale d'un avoir."""

    __tablename__ = "avoir_redemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    avoir_id: Mapped[int] = mapped_column(ForeignKey("avoirs.id"), nullable=False, index=True)
    sale_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sales.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    avoir: Mapped["Avoir"] = relationship(back_populates="redemptions")
