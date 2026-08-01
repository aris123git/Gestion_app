"""Assistant de gestion par règles métier (sans API IA)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.client import Client
from app.models.debt import ACTIVE_DEBT_STATUSES, Debt
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.services.dashboard_service import DashboardService
from app.services.inventory_service import InventoryService
from app.services.supplier_debt_service import SupplierDebtService


@dataclass
class Recommendation:
    level: str  # info | warning | danger
    title: str
    detail: str
    category: str


class AssistantService:
    """Génère des recommandations à partir des données locales."""

    @classmethod
    def recommendations(cls) -> List[Recommendation]:
        items: List[Recommendation] = []
        items.extend(cls._stock_alerts())
        items.extend(cls._debt_alerts())
        items.extend(cls._dormant_products())
        items.extend(cls._sales_trend())
        items.extend(cls._client_dependency())
        items.extend(cls._supplier_debts())
        return items

    @staticmethod
    def _stock_alerts() -> List[Recommendation]:
        out: List[Recommendation] = []
        low = []
        with session_scope() as session:
            low = list(
                session.scalars(
                    select(Product).where(
                        Product.is_active.is_(True),
                        Product.quantity <= Product.min_stock,
                    ).limit(20)
                ).all()
            )
            for p in low:
                session.expunge(p)
        for product in low:
            if float(product.quantity) <= 0:
                out.append(
                    Recommendation(
                        "danger",
                        f"Rupture : {product.name}",
                        "Réapprovisionner immédiatement.",
                        "stock",
                    )
                )
            else:
                forecast = InventoryService.stockout_forecast(product.id)
                days = forecast.get("days_left")
                detail = (
                    f"Stock {float(product.quantity):g}. "
                    f"Rupture estimée dans {days} jour(s)."
                    if days is not None
                    else f"Stock faible ({float(product.quantity):g})."
                )
                out.append(
                    Recommendation(
                        "warning",
                        f"Stock faible : {product.name}",
                        detail + " Proposer un réapprovisionnement.",
                        "stock",
                    )
                )
        return out

    @staticmethod
    def _debt_alerts() -> List[Recommendation]:
        out: List[Recommendation] = []
        today = date.today()
        with session_scope() as session:
            overdue = list(
                session.scalars(
                    select(Debt)
                    .where(
                        Debt.status.in_(ACTIVE_DEBT_STATUSES),
                        Debt.due_date.is_not(None),
                        Debt.due_date < today,
                        Debt.amount_remaining > 0,
                    )
                    .limit(20)
                ).all()
            )
            for d in overdue:
                client = session.get(Client, d.client_id)
                name = client.name if client else f"#{d.client_id}"
                out.append(
                    Recommendation(
                        "warning",
                        f"Dette échue — {name}",
                        f"Reste dû {float(d.amount_remaining):,.0f}. Relancer le client.",
                        "dette",
                    )
                )
        return out

    @staticmethod
    def _dormant_products() -> List[Recommendation]:
        out: List[Recommendation] = []
        for name, qty in DashboardService.dormant_products(days=30, limit=8):
            out.append(
                Recommendation(
                    "info",
                    f"Produit dormant : {name}",
                    f"Stock {qty:g} sans vente sur 30 j. Suggérer une promotion.",
                    "produit",
                )
            )
        return out

    @staticmethod
    def _sales_trend() -> List[Recommendation]:
        today = date.today()
        this_week = DashboardService._period_cash_revenue(
            today - timedelta(days=6), today
        )
        prev_week = DashboardService._period_cash_revenue(
            today - timedelta(days=13), today - timedelta(days=7)
        )
        if prev_week > 0 and this_week < prev_week * 0.8:
            drop = round((1 - this_week / prev_week) * 100)
            return [
                Recommendation(
                    "warning",
                    "Ventes en baisse",
                    f"CA 7 j en baisse d'environ {drop} % vs semaine précédente.",
                    "ventes",
                )
            ]
        return []

    @staticmethod
    def _client_dependency() -> List[Recommendation]:
        today = date.today()
        month_start = today.replace(day=1)
        best = DashboardService.best_client(month_start, today)
        if not best:
            return []
        name, amount = best
        total = DashboardService._period_revenue(month_start, today)
        if total <= 0:
            return []
        share = amount / total
        if share >= 0.30:
            return [
                Recommendation(
                    "danger",
                    "Dépendance client",
                    f"{name} représente {share:.0%} du CA du mois. Diversifier la clientèle.",
                    "client",
                )
            ]
        return []

    @staticmethod
    def _supplier_debts() -> List[Recommendation]:
        total = SupplierDebtService.total_remaining()
        if total <= 0:
            return []
        return [
            Recommendation(
                "info",
                "Dettes fournisseurs",
                f"Solde dû aux fournisseurs : {total:,.0f}.",
                "fournisseur",
            )
        ]
