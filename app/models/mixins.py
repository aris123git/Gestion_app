"""Mixins réutilisables pour les modèles ORM."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Ajoute les colonnes de suivi de création / modification."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )
