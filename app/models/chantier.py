"""Chantiers / marchés : un marché = une mini-entreprise (encaissements, dépenses, avenants, avancement)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

STATUS_QUOTE = "devis"
STATUS_ACCEPTED = "accepte"
STATUS_RUNNING = "en_cours"
STATUS_DONE = "termine"
STATUS_PAID = "solde"
STATUS_DISPUTE = "litige"
STATUS_REFUSED = "refuse"

STATUS_LABELS = {
    STATUS_QUOTE: "Devis",
    STATUS_ACCEPTED: "Devis accepté",
    STATUS_RUNNING: "En cours",
    STATUS_DONE: "Terminé",
    STATUS_PAID: "Soldé",
    STATUS_DISPUTE: "Litige",
    STATUS_REFUSED: "Devis refusé",
}
# Statuts qui comptent dans les chiffres de l'entreprise (un devis, même accepté, n'est pas encore un marché).
MARKET_STATUSES = (STATUS_RUNNING, STATUS_DONE, STATUS_PAID, STATUS_DISPUTE)

EXPENSE_CATEGORIES = ["Matériel", "Main-d'œuvre", "Sous-traitant", "Transport", "Location d'engin", "Divers"]
PAYMENT_KINDS = ["Avance", "Tranche", "Solde", "Retenue de garantie"]


class Chantier(Base, TimestampMixin):
    __tablename__ = "chantiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    client_label: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_planned: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 3), default=0)          # montant convenu (prix du marché)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_RUNNING, index=True)
    progress_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)     # avancement saisi (mode manuel)
    progress_mode: Mapped[str] = mapped_column(String(10), default="manuel")  # « manuel » ou « lots »
    retention_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)    # retenue de garantie (information)
    notes: Mapped[str] = mapped_column(Text, default="")
    converted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    lines: Mapped[list["ChantierLine"]] = relationship(back_populates="chantier", cascade="all, delete-orphan")
    expenses: Mapped[list["ChantierExpense"]] = relationship(back_populates="chantier", cascade="all, delete-orphan")
    payments: Mapped[list["ChantierPayment"]] = relationship(back_populates="chantier", cascade="all, delete-orphan")
    addenda: Mapped[list["ChantierAddendum"]] = relationship(back_populates="chantier", cascade="all, delete-orphan")
    lots: Mapped[list["ChantierLot"]] = relationship(back_populates="chantier", cascade="all, delete-orphan")
    milestones: Mapped[list["ChantierMilestone"]] = relationship(back_populates="chantier", cascade="all, delete-orphan")
    budgets: Mapped[list["ChantierBudget"]] = relationship(back_populates="chantier", cascade="all, delete-orphan")


class ChantierLine(Base):
    """Ligne de devis ; devient le budget prévisionnel du marché."""

    __tablename__ = "chantier_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chantier_id: Mapped[int] = mapped_column(ForeignKey("chantiers.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), default=1)
    unit: Mapped[str] = mapped_column(String(30), default="")
    unit_price: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    category: Mapped[str] = mapped_column(String(50), default="Matériel")

    chantier: Mapped[Chantier] = relationship(back_populates="lines")

    @property
    def total(self) -> float:
        return round(float(self.quantity or 0) * float(self.unit_price or 0), 3)


class ChantierExpense(Base, TimestampMixin):
    __tablename__ = "chantier_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chantier_id: Mapped[int] = mapped_column(ForeignKey("chantiers.id"), index=True)
    category: Mapped[str] = mapped_column(String(50), default="Matériel")
    label: Mapped[str] = mapped_column(String(200), default="")
    supplier: Mapped[str] = mapped_column(String(200), default="")
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    amount: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    amount_paid: Mapped[float] = mapped_column(Numeric(14, 3), default=0)     # le reste = dette envers le fournisseur
    worker: Mapped[str] = mapped_column(String(120), default="")              # main-d'œuvre : nom de l'ouvrier
    days: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    daily_rate: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    attachment: Mapped[str] = mapped_column(String(300), default="")          # reçu / facture / photo (chemin relatif)
    notes: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    chantier: Mapped[Chantier] = relationship(back_populates="expenses")


class ChantierPayment(Base, TimestampMixin):
    """Encaissement : avance, tranche, solde."""

    __tablename__ = "chantier_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chantier_id: Mapped[int] = mapped_column(ForeignKey("chantiers.id"), index=True)
    number: Mapped[str] = mapped_column(String(30), default="")
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    kind: Mapped[str] = mapped_column(String(30), default="Tranche")
    amount: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    method: Mapped[str] = mapped_column(String(40), default="Espèces")
    reference: Mapped[str] = mapped_column(String(120), default="")
    attachment: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    chantier: Mapped[Chantier] = relationship(back_populates="payments")


class ChantierAddendum(Base, TimestampMixin):
    """Avenant : travaux supplémentaires (ou moins-value) avec trace écrite ; modifie le montant du marché."""

    __tablename__ = "chantier_addenda"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chantier_id: Mapped[int] = mapped_column(ForeignKey("chantiers.id"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    label: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[float] = mapped_column(Numeric(14, 3), default=0)          # peut être négatif
    notes: Mapped[str] = mapped_column(Text, default="")
    attachment: Mapped[str] = mapped_column(String(300), default="")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    chantier: Mapped[Chantier] = relationship(back_populates="addenda")


class ChantierLot(Base):
    """Lot de travaux avec son poids dans le marché : l'avancement = somme des poids des lots terminés."""

    __tablename__ = "chantier_lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chantier_id: Mapped[int] = mapped_column(ForeignKey("chantiers.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    weight: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    done: Mapped[bool] = mapped_column(Boolean, default=False)

    chantier: Mapped[Chantier] = relationship(back_populates="lots")


class ChantierMilestone(Base):
    """Échéancier prévu des encaissements (ex. 30 % à la signature)."""

    __tablename__ = "chantier_milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chantier_id: Mapped[int] = mapped_column(ForeignKey("chantiers.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    chantier: Mapped[Chantier] = relationship(back_populates="milestones")


class ChantierBudget(Base):
    """Budget de dépenses prévu par poste (matériel, main-d'œuvre…) : comparé au dépensé réel."""

    __tablename__ = "chantier_budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chantier_id: Mapped[int] = mapped_column(ForeignKey("chantiers.id"), index=True)
    category: Mapped[str] = mapped_column(String(50))
    amount: Mapped[float] = mapped_column(Numeric(14, 3), default=0)

    chantier: Mapped[Chantier] = relationship(back_populates="budgets")
