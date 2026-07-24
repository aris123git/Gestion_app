"""Utilisateurs de l'application (administrateur / gestionnaire / caissier)."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """Compte utilisateur avec rôle et permissions."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="Caissier")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def is_admin(self) -> bool:
        return self.role == "Administrateur"

    @property
    def is_manager(self) -> bool:
        return self.role == "Gestionnaire"

    @property
    def is_cashier(self) -> bool:
        return self.role == "Caissier"

    def can(self, permission: str) -> bool:
        from app.services import permissions as perms

        return perms.can(self, permission)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User {self.username!r} ({self.role})>"
