"""Rappels saisis à la main (une fois, ou répétés chaque jour / semaine / mois)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import TimestampMixin

REPEAT_NONE, REPEAT_DAILY, REPEAT_WEEKLY, REPEAT_MONTHLY = "", "daily", "weekly", "monthly"


class Reminder(Base, TimestampMixin):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    repeat: Mapped[str] = mapped_column(String(10), default=REPEAT_NONE)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
