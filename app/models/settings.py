"""Informations du commerce et paramètres clé/valeur."""

from __future__ import annotations

from sqlalchemy import Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base
from app.models.mixins import TimestampMixin


class ShopInfo(Base, TimestampMixin):
    """Fiche d'identité du commerce (une seule ligne, id=1)."""

    __tablename__ = "shop_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(200), default="Mon Commerce")
    shop_type: Mapped[str] = mapped_column(String(100), default="Boutique")
    address: Mapped[str] = mapped_column(String(300), default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    email: Mapped[str] = mapped_column(String(150), default="")
    currency: Mapped[str] = mapped_column(String(20), default="FCFA")
    logo_path: Mapped[str] = mapped_column(String(400), default="")
    vat_rate: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    ticket_footer: Mapped[str] = mapped_column(
        Text, default="Merci pour votre visite."
    )
    is_configured: Mapped[bool] = mapped_column(default=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<ShopInfo {self.name!r}>"


class Setting(Base):
    """Paramètre générique clé/valeur (préférences applicatives)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
