"""Service tableau de bord financier (indicateurs étendus)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.client import Client
from app.models.debt import ACTIVE_DEBT_STATUSES, Debt
from app.models.expense import Expense
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.models.supplier_debt import SupplierDebt
from app.services.supplier_debt_service import SupplierDebtService


def _range(start: date, end: date) -> Tuple[datetime, datetime]:
    return datetime.combine(start, time.min), datetime.combine(end, time.max)


class DashboardService:
    """Agrégations financières et commerciales pour le tableau de bord."""

    @staticmethod
    def _revenue(session, start: date, end: date) -> float:
        lo, hi = _range(start, end)
        return float(
            session.scalar(
                select(func.coalesce(func.sum(Sale.total), 0)).where(
                    Sale.date >= lo, Sale.date <= hi, Sale.status == "completed"
                )
            )
            or 0
        )

    @staticmethod
    def _profit(session, start: date, end: date) -> float:
        lo, hi = _range(start, end)
        return float(
            session.scalar(
                select(func.coalesce(func.sum(Sale.profit), 0)).where(
                    Sale.date >= lo, Sale.date <= hi, Sale.status == "completed"
                )
            )
            or 0
        )

    @staticmethod
    def _expenses(session, start: date, end: date) -> float:
        lo, hi = _range(start, end)
        return float(
            session.scalar(
                select(func.coalesce(func.sum(Expense.amount), 0)).where(
                    Expense.date >= lo, Expense.date <= hi
                )
            )
            or 0
        )

    @classmethod
    def financial_summary(cls) -> dict:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)
        with session_scope() as session:
            revenue = cls._revenue(session, today, today)
            profit_gross = cls._profit(session, today, today)
            expenses = cls._expenses(session, today, today)
            client_debts = float(
                session.scalar(
                    select(func.coalesce(func.sum(Debt.amount_remaining), 0)).where(
                        Debt.status.in_(ACTIVE_DEBT_STATUSES)
                    )
                )
                or 0
            )
        supplier_debts = SupplierDebtService.total_remaining()
        # Trésorerie simplifiée : encaissements jour − dépenses jour
        treasury = round(revenue - expenses, 2)
        return {
            "revenue_today": revenue,
            "revenue_week": cls._period_revenue(week_start, today),
            "revenue_month": cls._period_revenue(month_start, today),
            "revenue_year": cls._period_revenue(year_start, today),
            "profit_gross_today": profit_gross,
            "profit_net_today": round(profit_gross - expenses, 2),
            "expenses_today": expenses,
            "treasury": treasury,
            "client_debts": client_debts,
            "supplier_debts": supplier_debts,
        }

    @classmethod
    def _period_revenue(cls, start: date, end: date) -> float:
        with session_scope() as session:
            return cls._revenue(session, start, end)

    @staticmethod
    def best_client(start: date, end: date) -> Optional[Tuple[str, float]]:
        lo, hi = _range(start, end)
        with session_scope() as session:
            row = session.execute(
                select(Client.name, func.sum(Sale.total))
                .join(Sale, Sale.client_id == Client.id)
                .where(
                    Sale.date >= lo, Sale.date <= hi, Sale.status == "completed"
                )
                .group_by(Client.id)
                .order_by(func.sum(Sale.total).desc())
                .limit(1)
            ).first()
            if not row:
                return None
            return str(row[0]), float(row[1] or 0)

    @classmethod
    def best_clients_periods(cls) -> dict:
        today = date.today()
        return {
            "day": cls.best_client(today, today),
            "week": cls.best_client(today - timedelta(days=today.weekday()), today),
            "month": cls.best_client(today.replace(day=1), today),
            "year": cls.best_client(today.replace(month=1, day=1), today),
        }

    @staticmethod
    def top_product_by_qty(days: int = 30) -> Optional[Tuple[str, float]]:
        since = datetime.now() - timedelta(days=days)
        with session_scope() as session:
            row = session.execute(
                select(SaleItem.product_name, func.sum(SaleItem.quantity))
                .join(Sale, Sale.id == SaleItem.sale_id)
                .where(Sale.status == "completed", Sale.date >= since)
                .group_by(SaleItem.product_name)
                .order_by(func.sum(SaleItem.quantity).desc())
                .limit(1)
            ).first()
            return (str(row[0]), float(row[1])) if row else None

    @staticmethod
    def top_product_by_profit(days: int = 30) -> Optional[Tuple[str, float]]:
        since = datetime.now() - timedelta(days=days)
        with session_scope() as session:
            profit_expr = func.sum(
                (SaleItem.unit_price - SaleItem.purchase_price) * SaleItem.quantity
            )
            row = session.execute(
                select(SaleItem.product_name, profit_expr)
                .join(Sale, Sale.id == SaleItem.sale_id)
                .where(Sale.status == "completed", Sale.date >= since)
                .group_by(SaleItem.product_name)
                .order_by(profit_expr.desc())
                .limit(1)
            ).first()
            return (str(row[0]), float(row[1] or 0)) if row else None

    @staticmethod
    def dormant_products(days: int = 30, limit: int = 20) -> List[Tuple[str, float]]:
        """Produits en stock sans vente sur la période."""
        since = datetime.now() - timedelta(days=days)
        with session_scope() as session:
            sold_ids = select(SaleItem.product_id).join(Sale).where(
                Sale.status == "completed",
                Sale.date >= since,
                SaleItem.product_id.is_not(None),
            )
            rows = session.execute(
                select(Product.name, Product.quantity)
                .where(
                    Product.is_active.is_(True),
                    Product.quantity > 0,
                    Product.id.not_in(sold_ids),
                )
                .order_by(Product.quantity.desc())
                .limit(limit)
            ).all()
            return [(str(n), float(q)) for n, q in rows]
