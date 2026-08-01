"""Service inventaire : sorties motivées et prévisions de rupture."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, select

from app import config
from app.database.connection import session_scope
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.models.stock import LOSS_REASONS, MOVEMENT_OUT, StockMovement
from app.services import audit_service
from app.utils.helpers import to_float


class InventoryService:
    """Règles métier stock (pertes normalisées + vitesse de vente)."""

    @staticmethod
    def loss_reasons() -> List[str]:
        return list(config.STOCK_LOSS_REASONS or LOSS_REASONS)

    @classmethod
    def record_loss(
        cls,
        product_id: int,
        quantity: float,
        reason: str,
        *,
        comment: str = "",
        user_id: Optional[int] = None,
        username: str = "",
    ) -> None:
        """Sortie de stock avec motif normalisé (casse, vol, etc.)."""
        quantity = to_float(quantity)
        if quantity <= 0:
            raise ValueError("Quantité invalide.")
        reason = (reason or "autre").strip().lower()
        if reason not in cls.loss_reasons():
            reason = "autre"
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                raise ValueError("Produit introuvable.")
            before = float(product.quantity)
            if quantity > before:
                raise ValueError(
                    f"Stock insuffisant : disponible {before:g}, demandé {quantity:g}."
                )
            after = before - quantity
            product.quantity = after
            note = reason
            if comment:
                note = f"{reason} — {comment.strip()}"
            session.add(
                StockMovement(
                    product_id=product_id,
                    movement_type=MOVEMENT_OUT,
                    quantity=quantity,
                    quantity_before=before,
                    quantity_after=after,
                    reason=note,
                    comment=(comment or "").strip(),
                    user_id=user_id,
                )
            )
        audit_service.log_action(
            "Perte stock",
            "Stock",
            f"product={product_id} qty={quantity} motif={reason}",
            user_id,
            username,
        )

    @staticmethod
    def sales_velocity(product_id: int, days: int = 30) -> float:
        """Quantité moyenne vendue par jour sur la fenêtre donnée."""
        since = datetime.now() - timedelta(days=days)
        with session_scope() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(SaleItem.quantity), 0))
                .join(Sale, Sale.id == SaleItem.sale_id)
                .where(
                    SaleItem.product_id == product_id,
                    Sale.status == "completed",
                    Sale.date >= since,
                )
            )
        return round(float(total or 0) / max(days, 1), 4)

    @classmethod
    def stockout_forecast(cls, product_id: int) -> dict:
        """Estime le nombre de jours avant rupture (règles métier, sans IA)."""
        with session_scope() as session:
            product = session.get(Product, product_id)
            if not product:
                return {"days_left": None, "velocity_7": 0, "velocity_30": 0}
            qty = float(product.quantity)
            name = product.name
        v7 = cls.sales_velocity(product_id, 7)
        v30 = cls.sales_velocity(product_id, 30)
        # Vitesse retenue : moyenne pondérée (plus de poids au 7j si actif).
        velocity = v7 if v7 > 0 else v30
        if velocity <= 0:
            days_left = None if qty > 0 else 0
        else:
            days_left = round(qty / velocity, 1)
        return {
            "product_id": product_id,
            "product_name": name,
            "quantity": qty,
            "velocity_7": v7,
            "velocity_30": v30,
            "days_left": days_left,
        }

    @classmethod
    def forecasts(cls, limit: int = 50) -> List[dict]:
        """Prévisions pour les produits actifs ayant du stock ou des ventes."""
        with session_scope() as session:
            products = list(
                session.scalars(
                    select(Product)
                    .where(Product.is_active.is_(True))
                    .order_by(Product.name)
                    .limit(500)
                ).all()
            )
            ids = [p.id for p in products]
        rows = [cls.stockout_forecast(pid) for pid in ids]
        # Priorise les ruptures proches.
        rows.sort(
            key=lambda r: (
                r["days_left"] is None,
                r["days_left"] if r["days_left"] is not None else 10**9,
            )
        )
        return rows[:limit]
