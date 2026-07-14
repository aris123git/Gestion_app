"""Contrôleur des rapports : agrégations sur une période donnée."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Dict, List, Tuple

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.expense import Expense
from app.models.sale import Payment, Sale, SaleItem


def period_bounds(kind: str, reference: date | None = None) -> Tuple[date, date]:
    """Retourne (début, fin) pour un type de période standard."""
    reference = reference or date.today()
    if kind == "Journalier":
        return reference, reference
    if kind == "Hebdomadaire":
        start = reference - timedelta(days=reference.weekday())
        return start, start + timedelta(days=6)
    if kind == "Mensuel":
        start = reference.replace(day=1)
        next_month = (start + timedelta(days=32)).replace(day=1)
        return start, next_month - timedelta(days=1)
    if kind == "Annuel":
        return date(reference.year, 1, 1), date(reference.year, 12, 31)
    return reference, reference


class ReportController:
    @staticmethod
    def build(start: date, end: date) -> Dict:
        """Construit un rapport complet pour la période [start, end]."""
        lo = datetime.combine(start, time.min)
        hi = datetime.combine(end, time.max)
        with session_scope() as session:
            revenue = float(
                session.scalar(
                    select(func.coalesce(func.sum(Sale.total), 0)).where(
                        Sale.date >= lo, Sale.date <= hi, Sale.status == "completed"
                    )
                )
                or 0
            )
            profit = float(
                session.scalar(
                    select(func.coalesce(func.sum(Sale.profit), 0)).where(
                        Sale.date >= lo, Sale.date <= hi, Sale.status == "completed"
                    )
                )
                or 0
            )
            sales_count = int(
                session.scalar(
                    select(func.count()).select_from(Sale).where(
                        Sale.date >= lo, Sale.date <= hi, Sale.status == "completed"
                    )
                )
                or 0
            )
            expenses = float(
                session.scalar(
                    select(func.coalesce(func.sum(Expense.amount), 0)).where(
                        Expense.date >= lo, Expense.date <= hi
                    )
                )
                or 0
            )

            top = session.execute(
                select(
                    SaleItem.product_name,
                    func.sum(SaleItem.quantity),
                    func.sum(SaleItem.line_total),
                )
                .join(Sale, Sale.id == SaleItem.sale_id)
                .where(Sale.date >= lo, Sale.date <= hi, Sale.status == "completed")
                .group_by(SaleItem.product_name)
                .order_by(func.sum(SaleItem.line_total).desc())
                .limit(10)
            ).all()

            by_method = session.execute(
                select(Payment.method, func.sum(Payment.amount))
                .join(Sale, Sale.id == Payment.sale_id)
                .where(Sale.date >= lo, Sale.date <= hi, Sale.status == "completed")
                .group_by(Payment.method)
            ).all()

            by_expense_cat = session.execute(
                select(Expense.category, func.sum(Expense.amount))
                .where(Expense.date >= lo, Expense.date <= hi)
                .group_by(Expense.category)
            ).all()

        return {
            "start": start,
            "end": end,
            "revenue": revenue,
            "profit": profit,
            "net_profit": profit - expenses,
            "sales_count": sales_count,
            "expenses": expenses,
            "top_products": [(r[0], float(r[1] or 0), float(r[2] or 0)) for r in top],
            "payments": [(r[0], float(r[1] or 0)) for r in by_method],
            "expense_breakdown": [
                (r[0], float(r[1] or 0)) for r in by_expense_cat
            ],
        }

    @staticmethod
    def sales_rows(start: date, end: date) -> List[Tuple]:
        """Lignes détaillées des ventes pour export (Excel/PDF)."""
        lo = datetime.combine(start, time.min)
        hi = datetime.combine(end, time.max)
        with session_scope() as session:
            sales = session.scalars(
                select(Sale)
                .where(Sale.date >= lo, Sale.date <= hi)
                .order_by(Sale.date)
            ).all()
            rows = [
                (
                    s.ticket_number,
                    s.date.strftime("%d/%m/%Y %H:%M"),
                    float(s.total),
                    float(s.profit),
                    s.status,
                )
                for s in sales
            ]
        return rows
