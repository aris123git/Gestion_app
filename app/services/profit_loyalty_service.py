"""Fidélité : crédit % sur le bénéfice client (seuil fixé par l'admin).

Quand le bénéfice cumulé d'un client franchit un (ou plusieurs) seuils
configurés, un avoir « Fidélité bénéfices » est créé. En caisse, ce crédit
ne s'utilise que pour offrir un produit de la boutique (jamais une remise
en argent). Le reste de crédit n'apparaît sur le ticket que s'il est
strictement positif.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.connection import session_scope
from app.models.avoir import ACTIVE_AVOIR_STATUSES, Avoir
from app.models.client import Client
from app.models.profit_loyalty import ClientProfitLoyalty
from app.models.sale import Sale
from app.services import audit_service, settings_service
from app.utils.helpers import to_float

SETTING_ENABLED = "profit_loyalty_enabled"
SETTING_THRESHOLD = "profit_loyalty_threshold"
SETTING_PERCENT = "profit_loyalty_percent"

REASON_PREFIX = "Fidélité bénéfices"

DEFAULT_THRESHOLD = 50_000.0
DEFAULT_PERCENT = 10.0


class ProfitLoyaltyService:
    # --- Réglages (admin) -------------------------------------------------
    @staticmethod
    def is_enabled() -> bool:
        return settings_service.get_setting(SETTING_ENABLED, "0") == "1"

    @staticmethod
    def get_threshold() -> float:
        raw = settings_service.get_setting(
            SETTING_THRESHOLD, str(int(DEFAULT_THRESHOLD))
        )
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return DEFAULT_THRESHOLD

    @staticmethod
    def get_percent() -> float:
        raw = settings_service.get_setting(
            SETTING_PERCENT, str(int(DEFAULT_PERCENT))
        )
        try:
            return max(0.0, min(100.0, float(raw)))
        except (TypeError, ValueError):
            return DEFAULT_PERCENT

    @classmethod
    def get_config(cls) -> dict:
        return {
            "enabled": cls.is_enabled(),
            "threshold": cls.get_threshold(),
            "percent": cls.get_percent(),
        }

    @classmethod
    def set_config(
        cls,
        *,
        enabled: bool,
        threshold: float,
        percent: float,
        user_id: Optional[int] = None,
        username: str = "",
    ) -> None:
        threshold = max(0.0, float(threshold))
        percent = max(0.0, min(100.0, float(percent)))
        settings_service.set_setting(SETTING_ENABLED, "1" if enabled else "0")
        settings_service.set_setting(SETTING_THRESHOLD, str(round(threshold, 2)))
        settings_service.set_setting(SETTING_PERCENT, str(round(percent, 2)))
        audit_service.log_action(
            "Fidélité bénéfices",
            "Setting",
            f"actif={int(bool(enabled))} seuil={threshold:g} %={percent:g}",
            user_id,
            username,
        )

    # --- Calculs client ---------------------------------------------------
    @staticmethod
    def client_purchase_total(client_id: int) -> float:
        """Somme des totaux des ventes complétées du client."""
        with session_scope() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(Sale.total), 0)).where(
                    Sale.client_id == client_id,
                    Sale.status == "completed",
                )
            )
            return float(total or 0)

    @staticmethod
    def client_profit_total(client_id: int) -> float:
        """Somme des bénéfices générés par les ventes complétées du client."""
        with session_scope() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(Sale.profit), 0)).where(
                    Sale.client_id == client_id,
                    Sale.status == "completed",
                )
            )
            return float(total or 0)

    @staticmethod
    def _ensure_tracker(session: Session, client_id: int) -> ClientProfitLoyalty:
        row = session.scalar(
            select(ClientProfitLoyalty).where(
                ClientProfitLoyalty.client_id == client_id
            )
        )
        if row:
            return row
        row = ClientProfitLoyalty(client_id=client_id, profit_rewarded=0)
        session.add(row)
        session.flush()
        return row

    @classmethod
    def credit_balance(cls, client_id: int) -> float:
        """Solde d'avoirs « Fidélité bénéfices » encore utilisables."""
        if not client_id:
            return 0.0
        with session_scope() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(Avoir.amount_remaining), 0)).where(
                    Avoir.client_id == client_id,
                    Avoir.status.in_(ACTIVE_AVOIR_STATUSES),
                    Avoir.reason.like(f"{REASON_PREFIX}%"),
                )
            )
            return round(float(total or 0), 2)

    @classmethod
    def ticket_remaining_line(cls, client_id: Optional[int]) -> Optional[float]:
        """Montant à imprimer sur le ticket, ou None si rien à écrire."""
        if not client_id or not cls.is_enabled():
            return None
        remaining = cls.credit_balance(int(client_id))
        if remaining > 0.01:
            return remaining
        return None

    @classmethod
    def grant_for_client(
        cls,
        client_id: int,
        *,
        sale_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> List[Avoir]:
        """Crée les avoirs pour chaque nouveau palier de bénéfice atteint."""
        if not client_id or not cls.is_enabled():
            return []
        threshold = cls.get_threshold()
        percent = cls.get_percent()
        if threshold <= 0 or percent <= 0:
            return []

        total_profit = cls.client_profit_total(client_id)
        created: List[Avoir] = []

        with session_scope() as session:
            tracker = cls._ensure_tracker(session, client_id)
            already = float(tracker.profit_rewarded or 0)
            tiers_now = int(total_profit // threshold)
            tiers_done = int(already // threshold)
            new_tiers = max(0, tiers_now - tiers_done)
            if new_tiers <= 0:
                return []

            reward_each = round(threshold * percent / 100.0, 2)
            if reward_each <= 0:
                return []

            client = session.get(Client, client_id)
            customer_name = client.name if client else ""

            for i in range(new_tiers):
                avoir = Avoir(
                    client_id=client_id,
                    customer_name=customer_name,
                    amount_initial=reward_each,
                    amount_remaining=reward_each,
                    reason=f"{REASON_PREFIX} (palier {tiers_done + i + 1})",
                    note=(
                        f"Bénéfice cumulé {total_profit:g} ≥ "
                        f"{(tiers_done + i + 1) * threshold:g} "
                        f"→ {percent:g} % du seuil"
                    ),
                    status="actif",
                    created_by=user_id,
                    sale_id=sale_id,
                )
                session.add(avoir)
                session.flush()
                created.append(avoir)

            tracker.profit_rewarded = round(already + new_tiers * threshold, 2)
            session.flush()
            for avoir in created:
                session.refresh(avoir)
                session.expunge(avoir)

        if created:
            audit_service.log_action(
                "Remise fidélité bénéfices",
                "Avoir",
                f"client={client_id} paliers={len(created)} "
                f"montant={len(created) * reward_each:g} sale={sale_id}",
                user_id,
                "",
            )
        return created

    @classmethod
    def redeem_credit(
        cls,
        client_id: int,
        amount: float,
        *,
        sale_id: Optional[int] = None,
    ) -> Tuple[float, float]:
        """Utilise le crédit fidélité (FIFO). Retourne (utilisé, reste)."""
        from app.models.avoir import (
            STATUS_PARTIAL,
            STATUS_USED,
            AvoirRedemption,
        )

        amount = round(to_float(amount), 2)
        if not client_id or amount <= 0:
            return 0.0, cls.credit_balance(client_id) if client_id else 0.0

        with session_scope() as session:
            avoirs = list(
                session.scalars(
                    select(Avoir)
                    .where(
                        Avoir.client_id == client_id,
                        Avoir.status.in_(ACTIVE_AVOIR_STATUSES),
                        Avoir.reason.like(f"{REASON_PREFIX}%"),
                        Avoir.amount_remaining > 0,
                    )
                    .order_by(Avoir.id.asc())
                ).all()
            )
            available = round(sum(float(a.amount_remaining) for a in avoirs), 2)
            to_use = min(amount, available)
            if to_use <= 0:
                return 0.0, available

            remaining_to_take = to_use
            for avoir in avoirs:
                if remaining_to_take <= 0.001:
                    break
                take = min(float(avoir.amount_remaining), remaining_to_take)
                new_rem = round(float(avoir.amount_remaining) - take, 2)
                avoir.amount_remaining = new_rem if new_rem > 0.001 else 0
                avoir.status = STATUS_USED if avoir.amount_remaining <= 0 else STATUS_PARTIAL
                session.add(
                    AvoirRedemption(
                        avoir_id=avoir.id,
                        sale_id=sale_id,
                        amount=take,
                        note="Utilisation caisse — remise fidélité",
                    )
                )
                remaining_to_take = round(remaining_to_take - take, 2)

            left = round(
                sum(
                    float(a.amount_remaining)
                    for a in avoirs
                    if a.status in ACTIVE_AVOIR_STATUSES
                ),
                2,
            )
            used = round(to_use - max(0.0, remaining_to_take), 2)
            return used, left

    @classmethod
    def client_summary(cls, client_id: int) -> dict:
        return {
            "purchase_total": cls.client_purchase_total(client_id),
            "profit_total": cls.client_profit_total(client_id),
            "credit_balance": cls.credit_balance(client_id),
            "threshold": cls.get_threshold(),
            "percent": cls.get_percent(),
            "enabled": cls.is_enabled(),
        }
