"""Alertes automatiques (stock, dettes en retard, boutiques à rappeler) et rappels saisis à la main."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, List, Optional

from sqlalchemy import select

from app.database.connection import session_scope
from app.models.debt import ACTIVE_DEBT_STATUSES, Debt
from app.models.reminder import REPEAT_DAILY, REPEAT_MONTHLY, REPEAT_NONE, REPEAT_WEEKLY, Reminder
from app.services import permissions as perms, settings_service

KIND_STOCK, KIND_DEBT, KIND_PROSPECT, KIND_REMINDER = "stock", "debts", "prospects", "reminders"
KINDS = (KIND_STOCK, KIND_DEBT, KIND_PROSPECT, KIND_REMINDER)
LABELS = {KIND_STOCK: "Stock bas et ruptures", KIND_DEBT: "Dettes de clients en retard",
          KIND_PROSPECT: "Boutiques à rappeler (tournées)", KIND_REMINDER: "Mes rappels"}
REPEATS = ((REPEAT_NONE, "Une seule fois"), (REPEAT_DAILY, "Chaque jour"), (REPEAT_WEEKLY, "Chaque semaine"), (REPEAT_MONTHLY, "Chaque mois"))


@dataclass
class Alert:
    kind: str
    text: str
    page: str = ""                 # page à ouvrir : ProductsPage, DebtsPage, FieldSalesPage…
    ref_id: Optional[int] = None   # produit à sélectionner
    reminder_id: Optional[int] = None
    upcoming: bool = False         # rappel à venir (pas encore dû)


def is_enabled(kind: str) -> bool:
    return settings_service.get_setting(f"alerts.{kind}", "1") != "0"


def set_enabled(kind: str, value: bool) -> None:
    settings_service.set_setting(f"alerts.{kind}", "1" if value else "0")


# -- rappels --------------------------------------------------------------------------------------------
def add_reminder(text: str, due: date, repeat: str = REPEAT_NONE) -> int:
    text = (text or "").strip()
    if not text:
        raise ValueError("Écrivez le texte du rappel.")
    with session_scope() as s:
        r = Reminder(text=text, due_date=due, repeat=repeat if repeat in dict(REPEATS) else REPEAT_NONE, done=False)
        s.add(r)
        s.flush()
        return r.id


def _next_due(due: date, repeat: str) -> date:
    if repeat == REPEAT_DAILY:
        return due + timedelta(days=1)
    if repeat == REPEAT_WEEKLY:
        return due + timedelta(days=7)
    m = due.month % 12 + 1
    y = due.year + (1 if due.month == 12 else 0)
    return date(y, m, min(due.day, calendar.monthrange(y, m)[1]))


def mark_done(reminder_id: int) -> None:
    """Rappel unique : terminé. Rappel répété : passe à la prochaine date (après aujourd'hui)."""
    with session_scope() as s:
        r = s.get(Reminder, reminder_id)
        if r is None:
            return
        if r.repeat in (REPEAT_DAILY, REPEAT_WEEKLY, REPEAT_MONTHLY):
            nxt = _next_due(r.due_date, r.repeat)
            while nxt <= date.today():
                nxt = _next_due(nxt, r.repeat)
            r.due_date = nxt
        else:
            r.done = True


def delete_reminder(reminder_id: int) -> None:
    with session_scope() as s:
        r = s.get(Reminder, reminder_id)
        if r is not None:
            s.delete(r)


def _reminder_alerts() -> List[Alert]:
    today = date.today()
    out: List[Alert] = []
    with session_scope() as s:
        for r in s.scalars(select(Reminder).where(Reminder.done.is_(False)).order_by(Reminder.due_date, Reminder.id)):
            due = r.due_date <= today
            when = "aujourd'hui" if r.due_date == today else (f"en retard depuis le {r.due_date:%d/%m}" if due else f"le {r.due_date:%d/%m/%Y}")
            out.append(Alert(KIND_REMINDER, f"{r.text} ({when})", reminder_id=r.id, upcoming=not due))
    return out


# -- alertes automatiques -----------------------------------------------------------------------------------------
def alerts(can: Optional[Callable[[str], bool]] = None, include_upcoming: bool = False) -> List[Alert]:
    can = can or (lambda _p: True)
    out: List[Alert] = []
    if is_enabled(KIND_STOCK) and (can(perms.VIEW_PRODUCTS) or can(perms.MANAGE_PRODUCTS)):
        from app.controllers.product_controller import ProductController

        low, empty = [], []
        for p in ProductController.list(limit=5000):
            if getattr(p, "sell_without_stock", False):
                continue
            if p.is_out_of_stock:
                empty.append(Alert(KIND_STOCK, f"{p.name} : rupture de stock", "ProductsPage", p.id))
            elif p.is_low_stock:
                from app.utils.helpers import format_quantity

                low.append(Alert(KIND_STOCK, f"{p.name} : stock bas ({format_quantity(p.quantity)})", "ProductsPage", p.id))
        out += empty + low
    if is_enabled(KIND_DEBT) and can(perms.MANAGE_CLIENT_DEBTS):
        from app.models.client import Client
        from app.utils.helpers import format_money

        cur = settings_service.get_currency()
        today = date.today()
        with session_scope() as s:
            by_client: dict = {}
            for d, name in s.execute(select(Debt, Client.name).join(Client, Client.id == Debt.client_id)
                                     .where(Debt.status.in_(ACTIVE_DEBT_STATUSES), Debt.due_date.is_not(None), Debt.due_date < today)):
                if float(d.amount_remaining) <= 0:
                    continue
                g = by_client.setdefault(d.client_id, {"name": name, "total": 0.0, "since": d.due_date})
                g["total"] += float(d.amount_remaining)
                g["since"] = min(g["since"], d.due_date)
            for g in sorted(by_client.values(), key=lambda g: g["since"]):
                out.append(Alert(KIND_DEBT, f"{g['name']} : {format_money(g['total'], cur)} en retard depuis le {g['since']:%d/%m/%Y}", "ClientsPage"))
    if is_enabled(KIND_PROSPECT) and can(perms.MANAGE_FIELD_SALES):
        from app.services import field_sales_service as fs

        if fs.enabled():
            now = datetime.now()
            for p in fs.prospects():
                if p.follow_up is not None and p.follow_up <= now and p.last_result in ("Intéressé", "À rappeler"):
                    out.append(Alert(KIND_PROSPECT, f"Rappeler la boutique {p.shop} (prévu le {p.follow_up:%d/%m})", "FieldSalesPage"))
    if is_enabled(KIND_REMINDER):
        out += [a for a in _reminder_alerts() if include_upcoming or not a.upcoming]
    return out


def count(can: Optional[Callable[[str], bool]] = None) -> int:
    return len(alerts(can))
