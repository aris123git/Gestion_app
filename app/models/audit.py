"""Journal d'audit des actions importantes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


class AuditLog(Base):
    """Enregistrement d'une action tracée (sécurité / historique)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    username: Mapped[str] = mapped_column(String(80), default="")
    action: Mapped[str] = mapped_column(String(100), default="")
    entity: Mapped[str] = mapped_column(String(80), default="")
    details: Mapped[str] = mapped_column(Text, default="")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AuditLog {self.action} {self.entity}>"
