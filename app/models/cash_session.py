"""Sessions de caisse (ouverture / fermeture avec fond et comptage)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin

STATUS_OPEN = "ouverte"
STATUS_CLOSED = "fermée"


class CashSession(Base, TimestampMixin):
    """Poste de caisse d'un utilisateur pour une vacation."""

    __tablename__ = "cash_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    opening_float: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    closing_counted: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    expected_cash: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    variance: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_OPEN, index=True)
    note: Mapped[str] = mapped_column(Text, default="")

    user: Mapped[Optional["User"]] = relationship()  # noqa: F821

    @property
    def is_open(self) -> bool:
        return self.status == STATUS_OPEN

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CashSession {self.id} user={self.user_id} {self.status}>"
