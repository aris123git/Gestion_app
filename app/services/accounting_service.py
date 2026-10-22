"""Comptabilité simplifiée : journal des opérations, résultat, TVA, trésorerie.

Version légère (pas de partie double) pensée pour être remise à un comptable :
toutes les données viennent des ventes, achats, dépenses et règlements déjà saisis.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import config
from app.database.connection import session_scope
from app.models.debt import DebtPayment
from app.models.expense import Expense
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.supplier_debt import SupplierDebtPayment

JOURNAL_HEADERS = ["Date", "Type", "Pièce", "Tiers", "Libellé", "Mode", "Entrée", "Sortie", "À crédit"]


def _f(value) -> float:
    return float(value or 0)


def build(start: date, end: date) -> dict:
    """Retourne journal, résultat, TVA et trésorerie pour [start, end]."""
    lo = datetime.combine(start, time.min)
    hi = datetime.combine(end, time.max)
    credit = config.PAYMENT_METHOD_CREDIT

    journal: list[tuple] = []  # (datetime, type, pièce, tiers, libellé, mode, entrée, sortie, crédit)
    inflow: dict[str, float] = defaultdict(float)
    ca_ttc = cmv = 0.0
    vat: dict[float, list] = defaultdict(lambda: [0.0, 0.0])
    cancelled_total = 0.0

    with session_scope() as session:
        sales = session.scalars(
            select(Sale)
            .options(joinedload(Sale.items), joinedload(Sale.payments), joinedload(Sale.client))
            .where(Sale.date >= lo, Sale.date <= hi)
            .order_by(Sale.date)
        ).unique().all()
        for sale in sales:
            client = sale.client.name if sale.client else ""
            if sale.status == "cancelled":
                cancelled_total += _f(sale.total)
                journal.append((sale.date, "Vente annulée", sale.ticket_number, client,
                                f"Annulée : {sale.cancel_reason or ''}".strip(), "", 0.0, 0.0, 0.0))
                continue
            if sale.status != "completed":
                continue
            ca_ttc += _f(sale.total)
            paid = {}
            on_credit = 0.0
            for pay in sale.payments:
                if pay.method == credit:
                    on_credit += _f(pay.amount)
                else:
                    paid[pay.method] = paid.get(pay.method, 0.0) + _f(pay.amount)
            for item in sale.items:
                qty, total, rate = _f(item.quantity), _f(item.line_total), _f(item.tax_rate)
                cmv += _f(item.purchase_price) * qty
                tax = total * rate / (100 + rate) if rate > 0 else 0.0
                vat[rate][0] += total
                vat[rate][1] += tax
            if not paid:
                journal.append((sale.date, "Vente", sale.ticket_number, client, "Vente à crédit", credit, 0.0, 0.0, on_credit))
            for i, (method, amount) in enumerate(sorted(paid.items())):
                inflow[method] += amount
                journal.append((sale.date, "Vente", sale.ticket_number, client, "Vente", method, amount, 0.0, on_credit if i == 0 else 0.0))

        for pay in session.scalars(
            select(DebtPayment).options(joinedload(DebtPayment.debt)).where(DebtPayment.payment_date >= lo, DebtPayment.payment_date <= hi)
        ).unique().all():
            who = ""
            try:
                who = pay.debt.client.name if pay.debt and pay.debt.client else ""
            except Exception:
                pass
            method = pay.payment_method or "Espèces"
            inflow[method] += _f(pay.amount)
            journal.append((pay.payment_date, "Règlement client", f"D-{pay.debt_id}", who, pay.note or "Règlement de dette", method, _f(pay.amount), 0.0, 0.0))

        purchases_total = purchases_paid = 0.0
        for pur in session.scalars(
            select(Purchase).options(joinedload(Purchase.supplier)).where(Purchase.date >= lo, Purchase.date <= hi, Purchase.status == "completed")
        ).unique().all():
            total, paid_amt = _f(pur.total), _f(pur.amount_paid)
            purchases_total += total
            purchases_paid += paid_amt
            journal.append((pur.date, "Achat", pur.invoice_number or f"A-{pur.id}", pur.supplier.name if pur.supplier else "",
                            "Achat de marchandises", "", 0.0, paid_amt, max(0.0, total - paid_amt)))

        supplier_paid = 0.0
        supplier_by_method: dict[str, float] = defaultdict(float)
        for pay in session.scalars(
            select(SupplierDebtPayment).options(joinedload(SupplierDebtPayment.debt)).where(
                SupplierDebtPayment.payment_date >= lo, SupplierDebtPayment.payment_date <= hi)
        ).unique().all():
            who = ""
            try:
                who = pay.debt.supplier.name if pay.debt and pay.debt.supplier else ""
            except Exception:
                pass
            method = pay.payment_method or "Espèces"
            supplier_paid += _f(pay.amount)
            supplier_by_method[method] += _f(pay.amount)
            journal.append((pay.payment_date, "Règlement fournisseur", f"F-{pay.debt_id}", who, pay.note or "Règlement de dette fournisseur", method, 0.0, _f(pay.amount), 0.0))

        expense_by_cat: dict[str, float] = defaultdict(float)
        expenses_total = 0.0
        for exp in session.scalars(select(Expense).where(Expense.date >= lo, Expense.date <= hi)).all():
            expense_by_cat[exp.category or "Autres"] += _f(exp.amount)
            expenses_total += _f(exp.amount)
            journal.append((exp.date, "Dépense", f"E-{exp.id}", "", f"{exp.category} — {exp.label}", "", 0.0, _f(exp.amount), 0.0))

    journal.sort(key=lambda r: r[0])
    journal_rows = [(r[0].strftime("%d/%m/%Y %H:%M"),) + tuple(r[1:]) for r in journal]
    vat_total = sum(v[1] for v in vat.values())
    ca_ht = ca_ttc - vat_total
    gross = ca_ht - cmv
    net = gross - expenses_total
    result = {
        "ca_ttc": round(ca_ttc, 3), "vat": round(vat_total, 3), "ca_ht": round(ca_ht, 3),
        "cmv": round(cmv, 3), "gross_margin": round(gross, 3),
        "expenses": sorted(((k, round(v, 3)) for k, v in expense_by_cat.items()), key=lambda r: r[1], reverse=True),
        "expenses_total": round(expenses_total, 3), "net": round(net, 3), "cancelled_total": round(cancelled_total, 3),
    }
    vat_rows = [(rate, round(ttc, 3), round(ttc - tax, 3), round(tax, 3)) for rate, (ttc, tax) in sorted(vat.items())]
    inflow_rows = sorted((m, round(a, 3)) for m, a in inflow.items())
    outflow_rows = [("Achats payés", round(purchases_paid, 3)), ("Règlements fournisseurs", round(supplier_paid, 3)), ("Dépenses", round(expenses_total, 3))]
    cash = {
        "inflows": inflow_rows, "outflows": outflow_rows,
        "total_in": round(sum(a for _, a in inflow_rows), 3),
        "total_out": round(purchases_paid + supplier_paid + expenses_total, 3),
        "balance": round(sum(a for _, a in inflow_rows) - purchases_paid - supplier_paid - expenses_total, 3),
        "purchases_on_credit": round(max(0.0, purchases_total - purchases_paid), 3),
    }
    return {"start": start, "end": end, "journal": journal_rows, "result": result, "vat": vat_rows, "cash": cash}


def result_rows(data: dict) -> list[tuple[str, float | None, bool]]:
    """Compte de résultat à plat : (libellé, montant, en gras)."""
    r = data["result"]
    rows: list[tuple[str, float | None, bool]] = [
        ("Ventes TTC", r["ca_ttc"], False),
        ("– TVA incluse", -r["vat"], False),
        ("Chiffre d'affaires hors taxe", r["ca_ht"], True),
        ("– Coût d'achat des marchandises vendues", -r["cmv"], False),
        ("Marge brute", r["gross_margin"], True),
    ]
    for cat, amount in r["expenses"]:
        rows.append((f"– Dépenses : {cat}", -amount, False))
    rows.append(("Total des dépenses", -r["expenses_total"], False))
    rows.append(("RÉSULTAT NET", r["net"], True))
    return rows
