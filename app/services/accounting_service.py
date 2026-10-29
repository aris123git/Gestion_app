"""Comptabilité en partie double (plan inspiré du SYSCOHADA).

Les écritures sont **générées à la volée** depuis les opérations déjà saisies
(ventes, achats, dépenses, règlements) puis complétées par les écritures
manuelles. Rien n'est dupliqué en base : le journal reste toujours cohérent
avec l'activité. Chaque écriture est équilibrée (total débit = total crédit).

Limites connues : les avoirs, ajustements de stock et pertes ne génèrent pas
d'écriture ; les dépenses et achats payés sont portés en caisse (leur mode de
paiement n'est pas enregistré) ; la TVA sur achats n'est suivie que via les
écritures manuelles.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import config
from app.database.connection import session_scope
from app.models.accounting import ManualEntry
from app.models.debt import Debt, DebtPayment
from app.models.expense import Expense
from app.models.pickup import STATUS_CLOSED, Pickup
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.supplier_debt import SupplierDebtPayment
from app.services.chart_of_accounts import CASH_ACCOUNTS, account_label, cash_account, expense_account

JOURNAL_NAMES = {
    "VT": "Journal des ventes",
    "AC": "Journal des achats",
    "CA": "Journal de trésorerie",
    "OD": "Opérations diverses",
}
JOURNAL_HEADERS = ["Date", "Journal", "Pièce", "Compte", "Libellé du compte", "Libellé", "Débit", "Crédit"]
EPS = 0.0005


@dataclass
class Entry:
    date: datetime
    journal: str
    piece: str
    label: str
    lines: list = field(default_factory=list)  # (compte, débit, crédit)

    def add(self, account: str, debit: float = 0.0, credit: float = 0.0) -> None:
        debit, credit = round(float(debit), 3), round(float(credit), 3)
        if debit or credit:
            self.lines.append((account, debit, credit))

    @property
    def balanced(self) -> bool:
        return abs(sum(l[1] for l in self.lines) - sum(l[2] for l in self.lines)) < EPS


def _f(value) -> float:
    return float(value or 0)


def generate_entries(upto: date) -> list[Entry]:
    """Toutes les écritures depuis le début de l'activité jusqu'à ``upto`` inclus."""
    hi = datetime.combine(upto, time.max)
    credit_method = config.PAYMENT_METHOD_CREDIT
    entries: list[Entry] = []

    with session_scope() as session:
        sales = session.scalars(
            select(Sale)
            .options(joinedload(Sale.items), joinedload(Sale.payments), joinedload(Sale.client))
            .where(Sale.date <= hi, Sale.status == "completed")
            .order_by(Sale.date)
        ).unique().all()
        for sale in sales:
            total = _f(sale.total)
            items_sum = sum(_f(i.line_total) for i in sale.items)
            ratio = (total / items_sum) if items_sum > 0 else 1.0
            tax = cmv = 0.0
            for item in sale.items:
                rate = _f(item.tax_rate)
                if rate > 0:
                    tax += _f(item.line_total) * ratio * rate / (100 + rate)
                cmv += _f(item.purchase_price) * _f(item.quantity)
            tax = round(tax, 3)
            who = sale.client.name if sale.client else ""
            entry = Entry(sale.date, "VT", sale.ticket_number, f"Vente {who}".strip())
            cash: dict[str, float] = defaultdict(float)
            receivable = 0.0
            for pay in sale.payments:
                if pay.method == credit_method:
                    receivable += _f(pay.amount)
                else:
                    cash[cash_account(pay.method)] += _f(pay.amount)
            diff = round(total - sum(cash.values()) - receivable, 3)
            if diff > 0:
                receivable += diff  # reste non encaissé → créance client
            elif diff < 0 and cash:
                last = list(cash)[-1]
                cash[last] = max(0.0, cash[last] + diff)
                receivable = max(0.0, total - sum(cash.values()))
            for acct, amount in cash.items():
                entry.add(acct, debit=amount)
            entry.add("411", debit=receivable)
            entry.add("701", credit=round(total - tax, 3))
            entry.add("4431", credit=tax)
            if entry.lines:
                entries.append(entry)
            if cmv > 0:
                cost = Entry(sale.date, "VT", sale.ticket_number, "Coût d'achat des marchandises vendues")
                cost.add("601", debit=cmv)
                cost.add("311", credit=cmv)
                entries.append(cost)

        for debt in session.scalars(
            select(Debt).options(joinedload(Debt.client)).where(Debt.sale_id.is_(None), Debt.status != "annulée")
        ).unique().all():
            if debt.created_at and debt.created_at <= hi:
                e = Entry(debt.created_at, "OD", f"D-{debt.id}", f"Créance {debt.client.name if debt.client else ''}".strip())
                e.add("411", debit=_f(debt.amount_initial))
                e.add("758", credit=_f(debt.amount_initial))
                entries.append(e)

        for pay in session.scalars(
            select(DebtPayment).options(joinedload(DebtPayment.debt).joinedload(Debt.client)).where(DebtPayment.payment_date <= hi)
        ).unique().all():
            who = pay.debt.client.name if pay.debt and pay.debt.client else ""
            e = Entry(pay.payment_date, "CA", f"D-{pay.debt_id}", f"Règlement client {who}".strip())
            e.add(cash_account(pay.payment_method), debit=_f(pay.amount))
            e.add("411", credit=_f(pay.amount))
            entries.append(e)

        for pur in session.scalars(
            select(Purchase).options(joinedload(Purchase.supplier)).where(Purchase.date <= hi, Purchase.status == "completed")
        ).unique().all():
            total, paid = _f(pur.total), min(_f(pur.amount_paid), _f(pur.total))
            e = Entry(pur.date, "AC", pur.invoice_number or f"A-{pur.id}", f"Achat {pur.supplier.name if pur.supplier else ''}".strip())
            e.add("311", debit=total)
            e.add("571", credit=paid)
            e.add("401", credit=round(total - paid, 3))
            entries.append(e)

        for pk in session.scalars(
            select(Pickup).options(joinedload(Pickup.items)).where(Pickup.status == STATUS_CLOSED, Pickup.closed_at <= hi)
        ).unique().all():
            loss = round(sum((_f(i.loss_quantity) - _f(i.billed_loss)) * _f(i.unit_cost) for i in pk.items), 3)
            if loss > 0 and pk.loss_bearer != "info":
                e = Entry(pk.closed_at, "OD", f"BE-{pk.number}", f"Perte sur enlèvement {pk.number} ({pk.loss_reason})")
                e.add("659", debit=loss)
                e.add("311", credit=loss)
                entries.append(e)

        for pay in session.scalars(
            select(SupplierDebtPayment).options(joinedload(SupplierDebtPayment.debt)).where(SupplierDebtPayment.payment_date <= hi)
        ).unique().all():
            who = ""
            try:
                who = pay.debt.supplier.name if pay.debt and pay.debt.supplier else ""
            except Exception:
                pass
            e = Entry(pay.payment_date, "CA", f"F-{pay.debt_id}", f"Règlement fournisseur {who}".strip())
            e.add("401", debit=_f(pay.amount))
            e.add(cash_account(pay.payment_method), credit=_f(pay.amount))
            entries.append(e)

        for exp in session.scalars(select(Expense).where(Expense.date <= hi)).all():
            e = Entry(exp.date, "CA", f"E-{exp.id}", f"{exp.category} — {exp.label}".strip(" —"))
            e.add(expense_account(exp.category), debit=_f(exp.amount))
            e.add("571", credit=_f(exp.amount))
            entries.append(e)

        for man in session.scalars(select(ManualEntry).where(ManualEntry.date <= hi)).all():
            e = Entry(man.date, "OD", f"M-{man.id}", man.label or "Écriture manuelle")
            e.add(man.debit_account, debit=_f(man.amount))
            e.add(man.credit_account, credit=_f(man.amount))
            entries.append(e)

    entries.sort(key=lambda e: e.date)
    return entries


def _flat(entries: list[Entry]) -> list[tuple]:
    """(date, journal, pièce, compte, libellé compte, libellé, débit, crédit) trié."""
    rows = []
    for e in entries:
        for acct, debit, credit in e.lines:
            rows.append((e.date, e.journal, e.piece, acct, account_label(acct), e.label, debit, credit))
    return rows


def _is_pl(account: str) -> bool:
    return account[:1] in ("6", "7")


def build(start: date, end: date) -> dict:
    """Journal, grand livre, balance, résultat, bilan, TVA et trésorerie."""
    lo = datetime.combine(start, time.min)
    hi = datetime.combine(end, time.max)
    entries = generate_entries(end)
    flat = _flat(entries)

    in_period = [r for r in flat if r[0] >= lo]
    journal = [(r[0].strftime("%d/%m/%Y %H:%M"),) + r[1:] for r in in_period]

    # Soldes d'ouverture : comptes de bilan avant le début de la période ; les
    # comptes de gestion (6/7) repartent de zéro (comme à l'ouverture d'un exercice).
    opening: dict[str, float] = defaultdict(float)
    moves: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    ledger: dict[str, list] = defaultdict(list)
    for date_, journal_code, piece, acct, _lab, label, debit, credit in flat:
        if date_ < lo:
            if not _is_pl(acct):
                opening[acct] += debit - credit
        else:
            moves[acct][0] += debit
            moves[acct][1] += credit
            ledger[acct].append((date_, journal_code, piece, label, debit, credit))

    accounts = sorted(set(opening) | set(moves))
    balance_rows = []
    for acct in accounts:
        op = opening.get(acct, 0.0)
        d, c = moves.get(acct, [0.0, 0.0])
        close = op + d - c
        balance_rows.append((
            acct, account_label(acct),
            round(op, 3) if op > 0 else 0.0, round(-op, 3) if op < 0 else 0.0,
            round(d, 3), round(c, 3),
            round(close, 3) if close > 0 else 0.0, round(-close, 3) if close < 0 else 0.0,
        ))

    general_ledger = {}
    for acct in accounts:
        run = opening.get(acct, 0.0)
        rows = []
        if abs(run) > EPS:
            rows.append(("", "", "", "Solde d'ouverture", round(run, 3) if run > 0 else 0.0, round(-run, 3) if run < 0 else 0.0, round(run, 3)))
        for date_, jc, piece, label, debit, credit in ledger.get(acct, []):
            run += debit - credit
            rows.append((date_.strftime("%d/%m/%Y %H:%M"), jc, piece, label, debit, credit, round(run, 3)))
        general_ledger[acct] = rows

    # --- Compte de résultat (période) ---------------------------------------
    def net(acct: str) -> float:
        d, c = moves.get(acct, [0.0, 0.0])
        return c - d  # positif = produit

    sales = net("701")
    other_products = sum(net(a) for a in moves if a[:1] == "7" and a != "701")
    purchases = -net("601")
    charges = [(a, account_label(a), -net(a)) for a in sorted(moves) if a[:1] == "6" and a != "601" and abs(net(a)) > EPS]
    charges_total = sum(c[2] for c in charges)
    commercial_margin = sales - purchases
    result = round(commercial_margin + other_products - charges_total, 3)
    income = {
        "sales": round(sales, 3), "purchases": round(purchases, 3), "margin": round(commercial_margin, 3),
        "other_products": round(other_products, 3), "charges": [(a, l, round(v, 3)) for a, l, v in charges],
        "charges_total": round(charges_total, 3), "result": result,
    }

    # --- Bilan à la date de fin (cumul depuis l'origine) -----------------------
    bal_all: dict[str, float] = defaultdict(float)
    pl_all = 0.0
    for _d, _j, _p, acct, _l, _lab, debit, credit in flat:
        if _is_pl(acct):
            pl_all += credit - debit
        else:
            bal_all[acct] += debit - credit
    assets = [(a, account_label(a), round(v, 3)) for a, v in sorted(bal_all.items()) if v > EPS]
    liabilities = [(a, account_label(a), round(-v, 3)) for a, v in sorted(bal_all.items()) if v < -EPS]
    liabilities.append(("12", "Résultat cumulé (bénéfice + / perte −)", round(pl_all, 3)))
    balance_sheet = {
        "assets": assets, "liabilities": liabilities,
        "total_assets": round(sum(a[2] for a in assets), 3), "total_liabilities": round(sum(l[2] for l in liabilities), 3),
    }

    # --- TVA (période) ---------------------------------------------------------
    collected = net("4431")
    deductible = -net("4452") + 0.0
    vat = {"collected": round(collected, 3), "deductible": round(deductible, 3), "due": round(collected - deductible, 3)}

    # --- Trésorerie par compte (période) ---------------------------------------
    cash_rows = []
    for acct in CASH_ACCOUNTS:
        op = opening.get(acct, 0.0)
        d, c = moves.get(acct, [0.0, 0.0])
        if abs(op) > EPS or d or c:
            cash_rows.append((acct, account_label(acct), round(op, 3), round(d, 3), round(c, 3), round(op + d - c, 3)))
    cash = {
        "rows": cash_rows,
        "total": round(sum(r[5] for r in cash_rows), 3),
    }

    unbalanced = [e.piece for e in entries if not e.balanced]
    return {
        "start": start, "end": end, "journal": journal, "ledger": general_ledger, "balance": balance_rows,
        "income": income, "sheet": balance_sheet, "vat": vat, "cash": cash, "unbalanced": unbalanced,
    }


def income_rows(data: dict) -> list[tuple[str, float, bool]]:
    r = data["income"]
    rows: list[tuple[str, float, bool]] = [
        ("Ventes de marchandises (701)", r["sales"], False),
        ("– Achats de marchandises vendues (601)", -r["purchases"], False),
        ("MARGE COMMERCIALE", r["margin"], True),
    ]
    if abs(r["other_products"]) > EPS:
        rows.append(("+ Autres produits (758…)", r["other_products"], False))
    for acct, label, amount in r["charges"]:
        rows.append((f"– {label} ({acct})", -amount, False))
    rows.append(("Total des charges d'exploitation", -r["charges_total"], False))
    rows.append(("RÉSULTAT NET", r["result"], True))
    return rows


# --- Écritures manuelles -----------------------------------------------------
def add_manual_entry(day: date, label: str, debit_account: str, credit_account: str, amount: float, user_id: int | None = None) -> int:
    from app.services.chart_of_accounts import CHART

    if debit_account not in CHART or credit_account not in CHART:
        raise ValueError("Compte inconnu.")
    if debit_account == credit_account:
        raise ValueError("Le compte débité et le compte crédité doivent être différents.")
    amount = round(float(amount), 3)
    if amount <= 0:
        raise ValueError("Le montant doit être positif.")
    with session_scope() as session:
        entry = ManualEntry(
            date=datetime.combine(day, datetime.now().time()), label=label.strip(),
            debit_account=debit_account, credit_account=credit_account, amount=amount, user_id=user_id,
        )
        session.add(entry)
        session.flush()
        return entry.id


def list_manual_entries() -> list[tuple]:
    with session_scope() as session:
        return [
            (m.id, m.date.strftime("%d/%m/%Y"), m.label, f"{m.debit_account} {account_label(m.debit_account)}",
             f"{m.credit_account} {account_label(m.credit_account)}", _f(m.amount))
            for m in session.scalars(select(ManualEntry).order_by(ManualEntry.date.desc())).all()
        ]


def delete_manual_entry(entry_id: int) -> None:
    with session_scope() as session:
        entry = session.get(ManualEntry, entry_id)
        if entry:
            session.delete(entry)


def suggested_opening_stock() -> tuple[float, date]:
    """Stock initial à saisir pour que le compte 311 reflète le stock réel.

    = valeur réelle du stock (quantité × prix d'achat) − solde actuel du compte 311.
    Daté du premier jour d'activité pour que les périodes passées restent cohérentes.
    """
    from app.models.product import Product

    entries = generate_entries(date.today())
    ledger = sum(l[1] - l[2] for e in entries for l in e.lines if l[0] == "311")
    with session_scope() as session:
        real = sum(
            _f(p.quantity) * _f(p.purchase_price)
            for p in session.scalars(select(Product).where(Product.is_active.is_(True))).all()
            if not getattr(p, "sell_without_stock", False)
        )
    first = min((e.date.date() for e in entries), default=date.today())
    return round(max(0.0, real - ledger), 3), first
