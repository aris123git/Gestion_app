"""Contrôleur des rapports : agrégations sur une période donnée."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Dict, List, Tuple

from sqlalchemy import func, select

from app import config
from app.database.connection import session_scope
from app.models.debt import DebtPayment
from app.models.expense import Expense
from app.models.sale import Payment, Sale, SaleItem
from app.models.supplier_debt import SupplierDebtPayment
from app.services import settings_service


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
    def z_report(day: date, *, user_id: int | None = None) -> Dict:
        """Résumé fin de caisse pour une journée (optionnellement un caissier)."""
        report = ReportController.build(day, day, user_id=user_id)
        report["day"] = day
        report["user_id"] = user_id
        return report

    @staticmethod
    def build(start: date, end: date, *, user_id: int | None = None) -> Dict:
        """Construit un rapport complet pour la période [start, end]."""
        lo = datetime.combine(start, time.min)
        hi = datetime.combine(end, time.max)
        sale_filters = [
            Sale.date >= lo,
            Sale.date <= hi,
            Sale.status == "completed",
        ]
        if user_id is not None:
            sale_filters.append(Sale.user_id == user_id)
        with session_scope() as session:
            total_sales = float(
                session.scalar(
                    select(func.coalesce(func.sum(Sale.total), 0)).where(*sale_filters)
                )
                or 0
            )
            sales_cash = float(
                session.scalar(
                    select(func.coalesce(func.sum(Payment.amount), 0))
                    .join(Sale, Sale.id == Payment.sale_id)
                    .where(
                        *sale_filters,
                        Payment.method != config.PAYMENT_METHOD_CREDIT,
                    )
                )
                or 0
            )
            credit_sales = float(
                session.scalar(
                    select(func.coalesce(func.sum(Payment.amount), 0))
                    .join(Sale, Sale.id == Payment.sale_id)
                    .where(
                        *sale_filters,
                        Payment.method == config.PAYMENT_METHOD_CREDIT,
                    )
                )
                or 0
            )
            profit = float(
                session.scalar(
                    select(func.coalesce(func.sum(Sale.profit), 0)).where(*sale_filters)
                )
                or 0
            )
            # Règlements de dettes hors vente (entrée libre) → bénéfice.
            from app.models.debt import Debt

            debt_pay_filters = [
                DebtPayment.payment_date >= lo,
                DebtPayment.payment_date <= hi,
            ]
            if user_id is not None:
                debt_pay_filters.append(DebtPayment.created_by == user_id)

            manual_debt_profit = float(
                session.scalar(
                    select(func.coalesce(func.sum(DebtPayment.amount), 0))
                    .join(Debt, Debt.id == DebtPayment.debt_id)
                    .where(
                        *debt_pay_filters,
                        Debt.sale_id.is_(None),
                    )
                )
                or 0
            )
            profit = round(profit + manual_debt_profit, 2)
            sales_count = int(
                session.scalar(
                    select(func.count()).select_from(Sale).where(*sale_filters)
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
            # Dépenses = magasin entier (pas filtrées par caissier).
            if user_id is not None:
                expenses = 0.0
            debt_repayments = float(
                session.scalar(
                    select(func.coalesce(func.sum(DebtPayment.amount), 0)).where(
                        *debt_pay_filters
                    )
                )
                or 0
            )
            supplier_debt_payments = float(
                session.scalar(
                    select(
                        func.coalesce(func.sum(SupplierDebtPayment.amount), 0)
                    ).where(
                        SupplierDebtPayment.payment_date >= lo,
                        SupplierDebtPayment.payment_date <= hi,
                    )
                )
                or 0
            )
            if user_id is not None:
                supplier_debt_payments = 0.0

            top = session.execute(
                select(
                    SaleItem.product_name,
                    func.sum(SaleItem.quantity),
                    func.sum(SaleItem.line_total),
                )
                .join(Sale, Sale.id == SaleItem.sale_id)
                .where(*sale_filters)
                .group_by(SaleItem.product_name)
                .order_by(func.sum(SaleItem.line_total).desc())
                .limit(10)
            ).all()

            by_method_rows = session.execute(
                select(Payment.method, func.sum(Payment.amount))
                .join(Sale, Sale.id == Payment.sale_id)
                .where(
                    *sale_filters,
                    Payment.method != config.PAYMENT_METHOD_CREDIT,
                )
                .group_by(Payment.method)
            ).all()
            # Les règlements de dettes clients comptent aussi dans le CA encaissé.
            debt_by_method = session.execute(
                select(DebtPayment.payment_method, func.sum(DebtPayment.amount)).where(
                    *debt_pay_filters
                ).group_by(DebtPayment.payment_method)
            ).all()

            by_expense_cat = session.execute(
                select(Expense.category, func.sum(Expense.amount))
                .where(Expense.date >= lo, Expense.date <= hi)
                .group_by(Expense.category)
            ).all()
            if user_id is not None:
                by_expense_cat = []

            # Ventilation par caissier (Z magasin uniquement).
            by_cashier: List[Tuple[str, float, int]] = []
            if user_id is None:
                from app.models.user import User

                cashier_rows = session.execute(
                    select(
                        func.coalesce(User.full_name, User.username, "—"),
                        func.coalesce(func.sum(Sale.total), 0),
                        func.count(Sale.id),
                    )
                    .select_from(Sale)
                    .outerjoin(User, User.id == Sale.user_id)
                    .where(
                        Sale.date >= lo,
                        Sale.date <= hi,
                        Sale.status == "completed",
                    )
                    .group_by(User.id)
                    .order_by(func.sum(Sale.total).desc())
                ).all()
                by_cashier = [
                    (str(name), float(total or 0), int(count or 0))
                    for name, total, count in cashier_rows
                ]

        method_totals: dict[str, float] = {}
        for method, amount in by_method_rows:
            method_totals[str(method)] = method_totals.get(str(method), 0.0) + float(
                amount or 0
            )
        for method, amount in debt_by_method:
            key = str(method or "Espèces")
            method_totals[key] = method_totals.get(key, 0.0) + float(amount or 0)
        by_method = sorted(method_totals.items(), key=lambda item: item[0])

        # CA encaissé = paiements de ventes (hors Dette) + règlements de dettes.
        cash_revenue = round(sales_cash + debt_repayments, 2)

        vat_rate = settings_service.get_vat_rate()
        vat_included = (
            round(total_sales * vat_rate / (100 + vat_rate), 2)
            if vat_rate > 0
            else 0.0
        )
        treasury = round(
            cash_revenue - expenses - supplier_debt_payments,
            2,
        )
        return {
            "start": start,
            "end": end,
            "user_id": user_id,
            "revenue": cash_revenue,
            "cash_revenue": cash_revenue,
            "sales_cash": sales_cash,
            "total_sales": total_sales,
            "credit_sales": credit_sales,
            "debt_repayments": debt_repayments,
            "supplier_debt_payments": supplier_debt_payments,
            "treasury": treasury,
            "vat_rate": vat_rate,
            "vat_included": vat_included,
            "profit": profit,
            "net_profit": profit - expenses,
            "sales_count": sales_count,
            "expenses": expenses,
            "top_products": [(r[0], float(r[1] or 0), float(r[2] or 0)) for r in top],
            "payments": [(r[0], float(r[1] or 0)) for r in by_method],
            "expense_breakdown": [
                (r[0], float(r[1] or 0)) for r in by_expense_cat
            ],
            "by_cashier": by_cashier,
        }

    @staticmethod
    def sales_rows(start: date, end: date) -> List[Tuple]:
        """Lignes détaillées des ventes pour export (Excel/PDF)."""
        lo = datetime.combine(start, time.min)
        hi = datetime.combine(end, time.max)
        with session_scope() as session:
            sales = session.scalars(
                select(Sale)
                .where(
                    Sale.date >= lo,
                    Sale.date <= hi,
                    Sale.status == "completed",
                )
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
