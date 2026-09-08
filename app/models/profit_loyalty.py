"""Suivi de la fidélité basée sur le bénéfice rapporté par chaque client."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class ClientProfitLoyalty(Base, TimestampMixin):
    """Compteur de bénéfice déjà converti en remises pour un client."""

    __tablename__ = "client_profit_loyalty"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"), nullable=False, unique=True, index=True
    )
    # Bénéfice cumulé déjà utilisé pour déclencher des paliers de remise.
    profit_rewarded: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    client: Mapped["Client"] = relationship()  # noqa: F821
