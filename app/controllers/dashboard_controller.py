"""Contrôleur du tableau de bord : agrégations et indicateurs clés."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Tuple

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.expense import Expense
from app.models.product import Product
from app.models.sale import Sale, SaleItem


def _range(start: date, end: date) -> Tuple[datetime, datetime]:
    return datetime.combine(start, time.min), datetime.combine(end, time.max)


class DashboardController:
    @staticmethod
    def _revenue(session, start: date, end: date) -> float:
        lo, hi = _range(start, end)
        total = session.scalar(
            select(func.coalesce(func.sum(Sale.total), 0)).where(
                Sale.date >= lo, Sale.date <= hi, Sale.status == "completed"
            )
        )
        return float(total or 0)

    @staticmethod
    def _profit(session, start: date, end: date) -> float:
        lo, hi = _range(start, end)
        total = session.scalar(
            select(func.coalesce(func.sum(Sale.profit), 0)).where(
                Sale.date >= lo, Sale.date <= hi, Sale.status == "completed"
            )
        )
        return float(total or 0)

    @staticmethod
    def _sales_count(session, start: date, end: date) -> int:
        lo, hi = _range(start, end)
        return int(
            session.scalar(
                select(func.count()).select_from(Sale).where(
                    Sale.date >= lo, Sale.date <= hi, Sale.status == "completed"
                )
            )
            or 0
        )

    @staticmethod
    def _expenses(session, start: date, end: date) -> float:
        lo, hi = _range(start, end)
        total = session.scalar(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                Expense.date >= lo, Expense.date <= hi
            )
        )
        return float(total or 0)

    @classmethod
    def summary(cls) -> dict:
        """Retourne l'ensemble des indicateurs affichés sur le tableau de bord."""
        today = date.today()
        month_start = today.replace(day=1)
        with session_scope() as session:
            revenue_today = cls._revenue(session, today, today)
            revenue_month = cls._revenue(session, month_start, today)
            sales_today = cls._sales_count(session, today, today)
            profit_today = cls._profit(session, today, today)
            expenses_today = cls._expenses(session, today, today)

            low_stock = session.scalar(
                select(func.count())
                .select_from(Product)
                .where(
                    Product.is_active.is_(True),
                    Product.quantity <= Product.min_stock,
                    Product.quantity > 0,
                )
            )
            out_of_stock = session.scalar(
                select(func.count())
                .select_from(Product)
                .where(Product.is_active.is_(True), Product.quantity <= 0)
            )
            total_products = session.scalar(
                select(func.count()).select_from(Product)
            )

        return {
            "revenue_today": revenue_today,
            "revenue_month": revenue_month,
            "sales_today": sales_today,
            "tickets_today": sales_today,
            "profit_today": profit_today - expenses_today,
            "expenses_today": expenses_today,
            "low_stock": int(low_stock or 0),
            "out_of_stock": int(out_of_stock or 0),
            "total_products": int(total_products or 0),
        }

    @staticmethod
    def top_products(limit: int = 5, days: int = 30) -> List[Tuple[str, float, float]]:
        """Produits les plus vendus : (nom, quantité, chiffre d'affaires)."""
        from datetime import timedelta

        since = datetime.now() - timedelta(days=days)
        with session_scope() as session:
            rows = session.execute(
                select(
                    SaleItem.product_name,
                    func.sum(SaleItem.quantity),
                    func.sum(SaleItem.line_total),
                )
                .join(Sale, Sale.id == SaleItem.sale_id)
                .where(Sale.date >= since, Sale.status == "completed")
                .group_by(SaleItem.product_name)
                .order_by(func.sum(SaleItem.quantity).desc())
                .limit(limit)
            ).all()
        return [(r[0], float(r[1] or 0), float(r[2] or 0)) for r in rows]
