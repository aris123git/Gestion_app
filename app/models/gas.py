"""Contrôle gaz : produits (bouteilles par formule), mouvements de stock, grossistes, livraisons, paiements.

Comptabilité à part : rien ici ne touche aux ventes, dettes ni caisse du logiciel (sauf option d'inclusion dans les totaux)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

FORMULA_RECHARGE, FORMULA_CONSIGNE, FORMULA_COMPLET = "recharge", "consigne", "complet"
FORMULAS = {FORMULA_RECHARGE: "Recharge", FORMULA_CONSIGNE: "Consigné", FORMULA_COMPLET: "Complet"}

MOVE_ENTRY, MOVE_SALE, MOVE_DELIVERY, MOVE_LOSS, MOVE_ADJUST = "entree", "vente", "livraison", "perte", "ajustement"
MOVE_TRANSFER = "transfert"      # retour du reste du camion au dépôt (+ côté dépôt, − côté camion)

TRIP_OPEN, TRIP_CLOSED = "en_cours", "termine"


class GasLine(Base, TimestampMixin):
    """Un produit gaz = une taille + une formule (ex. 6 kg Recharge) avec son stock et ses prix."""

    __tablename__ = "gas_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    size_kg: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    formula: Mapped[str] = mapped_column(String(20), default=FORMULA_RECHARGE)
    retail_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)       # prix détaillant / comptoir
    wholesale_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)    # prix grossiste
    cost_price: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)   # prix d'achat : vide = pas de bénéfice calculé
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class GasWholesaler(Base, TimestampMixin):
    __tablename__ = "gas_wholesalers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    phone: Mapped[str] = mapped_column(String(60), default="")
    address: Mapped[str] = mapped_column(String(250), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class GasDelivery(Base, TimestampMixin):
    __tablename__ = "gas_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wholesaler_id: Mapped[int] = mapped_column(ForeignKey("gas_wholesalers.id"), index=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[List["GasDeliveryItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class GasDeliveryItem(Base):
    __tablename__ = "gas_delivery_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("gas_deliveries.id", ondelete="CASCADE"), index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("gas_lines.id"))
    qty: Mapped[int] = mapped_column(Integer, default=0)                 # pleines livrées
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    empties_back: Mapped[int] = mapped_column(Integer, default=0)        # vides reçues en échange


class GasPayment(Base, TimestampMixin):
    __tablename__ = "gas_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wholesaler_id: Mapped[int] = mapped_column(ForeignKey("gas_wholesalers.id"), index=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    note: Mapped[str] = mapped_column(String(250), default="")


class GasMovement(Base):
    """Journal du stock (quantité signée) : le stock d'un produit = somme de ses mouvements."""

    __tablename__ = "gas_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    moved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("gas_lines.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    qty: Mapped[int] = mapped_column(Integer)                         # + entrée, − sortie
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    reason: Mapped[str] = mapped_column(String(250), default="")      # motif libre (pertes, ajustements)
    wholesaler_id: Mapped[Optional[int]] = mapped_column(ForeignKey("gas_wholesalers.id"), nullable=True)
    delivery_id: Mapped[Optional[int]] = mapped_column(ForeignKey("gas_deliveries.id"), nullable=True)
    trip_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)   # NULL = stock du dépôt ; sinon stock du camion


class GasTrip(Base, TimestampMixin):
    """Un voyage du camion : chargement à la source (ex. SONABHY), livraisons sur plusieurs jours, retour pour recharger."""

    __tablename__ = "gas_trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    truck: Mapped[str] = mapped_column(String(80), default="")
    driver: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(120), default="SONABHY")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=TRIP_OPEN, index=True)
    note: Mapped[str] = mapped_column(Text, default="")


class GasEmptiesReturn(Base):
    """Vides rendues à la source à la fin d'un voyage, par taille de bouteille (échange, aucun argent)."""

    __tablename__ = "gas_empties_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("gas_trips.id"), index=True)
    size_kg: Mapped[float] = mapped_column(Numeric(6, 2))
    proposed: Mapped[int] = mapped_column(Integer, default=0)     # calculé d'après les livraisons et ventes
    handed: Mapped[int] = mapped_column(Integer, default=0)       # réellement remis (modifiable)
