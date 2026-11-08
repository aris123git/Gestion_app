"""Ventes en tournée : vendeurs, sorties de marchandise (retour du soir), commissions, boutiques visitées."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

RUN_OPEN = "en_tournee"
RUN_CLOSED = "cloture"
VISIT_RESULTS = ["Vendu", "Intéressé", "À rappeler", "Refus"]

RULE_PERCENT = "pourcentage"
RULE_FIXED = "fixe"
SCOPE_PRODUCT, SCOPE_CATEGORY, SCOPE_DEFAULT = "produit", "categorie", "defaut"


class FieldSeller(Base, TimestampMixin):
    __tablename__ = "field_sellers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    phone: Mapped[str] = mapped_column(String(60), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    debt_client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)   # compte dette du vendeur


class FieldRun(Base, TimestampMixin):
    """Une sortie : le vendeur prend de la marchandise, vend dehors, rend le reste et l'argent le soir."""

    __tablename__ = "field_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("field_sellers.id"), index=True)
    out_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=RUN_OPEN, index=True)
    cash_received: Mapped[float] = mapped_column(Numeric(14, 3), default=0)   # argent remis au retour
    expected: Mapped[float] = mapped_column(Numeric(14, 3), default=0)        # vendu × prix, figé à la clôture
    shortage: Mapped[float] = mapped_column(Numeric(14, 3), default=0)        # attendu − remis (négatif = surplus)
    charged_to_seller: Mapped[bool] = mapped_column(Boolean, default=False)   # le manque est porté en dette du vendeur
    commission: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    commission_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    commission_paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sale_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sales.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    lines: Mapped[list["FieldRunLine"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    visits: Mapped[list["FieldVisit"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class FieldRunLine(Base):
    __tablename__ = "field_run_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("field_runs.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_name: Mapped[str] = mapped_column(String(200), default="")
    qty_out: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    qty_back: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 3), default=0)      # prix de vente
    commission: Mapped[float] = mapped_column(Numeric(14, 3), default=0)      # commission de la ligne, figée à la clôture

    run: Mapped[FieldRun] = relationship(back_populates="lines")


class FieldVisit(Base, TimestampMixin):
    """Boutique visitée pendant la sortie (créée à la volée, suivie jusqu'au rappel)."""

    __tablename__ = "field_visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("field_runs.id"), index=True)
    shop: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(60), default="", index=True)
    area: Mapped[str] = mapped_column(String(120), default="")
    result: Mapped[str] = mapped_column(String(30), default="Vendu")
    amount: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    follow_up: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")

    run: Mapped[FieldRun] = relationship(back_populates="visits")


class FieldCommissionRule(Base):
    """Règle de commission : par produit, par catégorie, ou règle par défaut."""

    __tablename__ = "field_commission_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(20), index=True)            # produit | categorie | defaut
    ref_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # id du produit / de la catégorie
    kind: Mapped[str] = mapped_column(String(20), default=RULE_PERCENT)    # pourcentage | fixe (par unité vendue)
    value: Mapped[float] = mapped_column(Numeric(14, 3), default=0)


class FieldCommissionPayment(Base, TimestampMixin):
    """Historique : commission payée à un vendeur pour une période (avec la dette déduite éventuelle)."""

    __tablename__ = "field_commission_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("field_sellers.id"), index=True)
    date_from: Mapped[datetime] = mapped_column(DateTime)
    date_to: Mapped[datetime] = mapped_column(DateTime)
    gross: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    debt_deducted: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    net_paid: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
