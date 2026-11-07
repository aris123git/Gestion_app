"""Main-d'œuvre : ouvriers, pointage par chantier, avances."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class Worker(Base, TimestampMixin):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    trade: Mapped[str] = mapped_column(String(80), default="")              # maçon, soudeur, menuisier…
    phone: Mapped[str] = mapped_column(String(60), default="")
    daily_rate: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkerDay(Base, TimestampMixin):
    """Pointage : un ouvrier a travaillé N jours (1, 0,5…) sur un chantier à une date."""

    __tablename__ = "worker_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    chantier_id: Mapped[int] = mapped_column(ForeignKey("chantiers.id"), index=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    days: Mapped[float] = mapped_column(Numeric(5, 2), default=1)
    rate: Mapped[float] = mapped_column(Numeric(14, 3), default=0)          # tarif du jour figé au pointage
    paid: Mapped[bool] = mapped_column(Boolean, default=False)              # inclus dans une paie
    notes: Mapped[str] = mapped_column(String(200), default="")


class WorkerAdvance(Base, TimestampMixin):
    __tablename__ = "worker_advances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    amount: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    deducted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
