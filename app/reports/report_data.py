"""Données détaillées pour les exports de rapports (Excel / PDF).

Complète ``ReportController.build`` avec les listes détaillées : lignes vendues,
ventes par jour, par caissier, dettes, dépenses, annulations, stock, marges, TVA.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.debt import ACTIVE_DEBT_STATUSES, Debt
from app.models.expense import Expense
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.models.supplier_debt import SupplierDebt
from app.models.supplier_debt import ACTIVE_DEBT_STATUSES as SUPPLIER_ACTIVE


def _f(value) -> float:
    return float(value or 0)


def _cashier(sale: Sale) -> str:
    user = sale.user
    return (user.full_name or user.username) if user else "—"


def collect_details(start: date, end: date) -> dict:
    """Retourne toutes les listes détaillées de la période [start, end]."""
    lo = datetime.combine(start, time.min)
    hi = datetime.combine(end, time.max)
    today = date.today()

    with session_scope() as session:
        sales = session.scalars(
            select(Sale)
            .options(joinedload(Sale.items), joinedload(Sale.user), joinedload(Sale.client), joinedload(Sale.payments))
            .where(Sale.date >= lo, Sale.date <= hi)
            .order_by(Sale.date)
        ).unique().all()

        lines, cancelled = [], []
        daily: dict[date, list] = defaultdict(lambda: [0, 0.0, 0.0, 0.0])  # nb, total, remises, profit
        hourly: dict[int, list] = defaultdict(lambda: [0, 0.0])
        cashiers: dict[str, list] = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0, 0.0])  # nb, ca, remises, profit, annul., montant annulé
        vat: dict[float, list] = defaultdict(lambda: [0.0, 0.0])  # ttc, tva
        products: dict[str, list] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # qté, ca, coût, tva
        for sale in sales:
            who = _cashier(sale)
            client = sale.client.name if sale.client else ""
            if sale.status == "cancelled":
                cancelled.append((
                    sale.ticket_number, sale.date.strftime("%d/%m/%Y %H:%M"), who, client,
                    _f(sale.total), sale.cancel_reason or "",
                ))
                row = cashiers[who]
                row[4] += 1
                row[5] += _f(sale.total)
                continue
            if sale.status != "completed":
                continue
            day = sale.date.date()
            d = daily[day]
            d[0] += 1
            d[1] += _f(sale.total)
            d[2] += _f(sale.discount)
            d[3] += _f(sale.profit)
            h = hourly[sale.date.hour]
            h[0] += 1
            h[1] += _f(sale.total)
            c = cashiers[who]
            c[0] += 1
            c[1] += _f(sale.total)
            c[2] += _f(sale.discount)
            c[3] += _f(sale.profit)
            methods = ", ".join(sorted({p.method for p in sale.payments}))
            for item in sale.items:
                qty, unit, total = _f(item.quantity), _f(item.unit_price), _f(item.line_total)
                cost = _f(item.purchase_price) * qty
                rate = _f(item.tax_rate)
                tax = total * rate / (100 + rate) if rate > 0 else 0.0
                lines.append((
                    sale.date.strftime("%d/%m/%Y %H:%M"), sale.ticket_number, item.product_name,
                    qty, unit, total, who, client, methods, cost, total - cost, rate, tax,
                ))
                p = products[item.product_name]
                p[0] += qty
                p[1] += total
                p[2] += cost
                p[3] += tax
                v = vat[rate]
                v[0] += total
                v[1] += tax

        expenses = [
            (e.date.strftime("%d/%m/%Y"), e.category, e.label, _f(e.amount), e.notes or "")
            for e in session.scalars(
                select(Expense).where(Expense.date >= lo, Expense.date <= hi).order_by(Expense.date)
            ).all()
        ]

        client_debts = []
        for debt in session.scalars(
            select(Debt).options(joinedload(Debt.client)).where(Debt.status.in_(ACTIVE_DEBT_STATUSES))
        ).unique().all():
            created = getattr(debt, "created_at", None)
            age = (today - created.date()).days if created else ""
            late = bool(debt.due_date and debt.due_date < today)
            client_debts.append((
                debt.client.name if debt.client else "—", debt.client.phone if debt.client else "",
                created.strftime("%d/%m/%Y") if created else "",
                debt.due_date.strftime("%d/%m/%Y") if debt.due_date else "",
                _f(debt.amount_initial), _f(debt.amount_remaining), age,
                "En retard" if late else "", debt.note or "",
            ))
        client_debts.sort(key=lambda r: r[5], reverse=True)

        supplier_debts = []
        for debt in session.scalars(
            select(SupplierDebt).options(joinedload(SupplierDebt.supplier)).where(SupplierDebt.status.in_(SUPPLIER_ACTIVE))
        ).unique().all():
            supplier_debts.append((
                debt.supplier.name if debt.supplier else "—",
                debt.due_date.strftime("%d/%m/%Y") if debt.due_date else "",
                _f(debt.amount_initial), _f(debt.amount_remaining),
                "En retard" if debt.due_date and debt.due_date < today else "", debt.note or "",
            ))
        supplier_debts.sort(key=lambda r: r[3], reverse=True)

        stock = []
        for p in session.scalars(
            select(Product).options(joinedload(Product.category)).where(Product.is_active.is_(True)).order_by(Product.name)
        ).unique().all():
            qty = _f(p.quantity)
            tracked = not getattr(p, "sell_without_stock", False)
            sold = products.get(p.name, [0, 0, 0, 0])[0]
            if not tracked:
                state = "Non suivi"
            elif qty <= 0:
                state = "Rupture"
            elif qty <= _f(p.min_stock):
                state = "Stock bas"
            elif sold == 0:
                state = "Sans vente"
            else:
                state = "OK"
            stock.append((
                p.name, p.category.name if p.category else "", qty if tracked else None,
                _f(p.min_stock), _f(p.purchase_price), _f(p.sale_price),
                qty * _f(p.purchase_price) if tracked else 0.0,
                qty * _f(p.sale_price) if tracked else 0.0, sold, state,
            ))

    daily_rows = [(day.strftime("%d/%m/%Y"), v[0], v[1], v[2], v[3]) for day, v in sorted(daily.items())]
    hourly_rows = [(f"{h:02d}h-{h + 1:02d}h", v[0], v[1]) for h, v in sorted(hourly.items())]
    cashier_rows = sorted(
        ((name, v[0], v[1], v[2], v[3], v[4], v[5]) for name, v in cashiers.items()),
        key=lambda r: r[2], reverse=True,
    )
    margin_rows = sorted(
        ((name, v[0], v[1], v[2], v[1] - v[2], ((v[1] - v[2]) / v[1] * 100) if v[1] else 0.0) for name, v in products.items()),
        key=lambda r: r[4], reverse=True,
    )
    vat_rows = [(rate, round(ttc, 3), round(ttc - tax, 3), round(tax, 3)) for rate, (ttc, tax) in sorted(vat.items())]
    return {
        "lines": lines,
        "daily": daily_rows,
        "hourly": hourly_rows,
        "cashiers": cashier_rows,
        "client_debts": client_debts,
        "supplier_debts": supplier_debts,
        "expenses": expenses,
        "cancelled": cancelled,
        "stock": stock,
        "margins": margin_rows,
        "vat": vat_rows,
    }
