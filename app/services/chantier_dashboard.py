"""Tableau de bord Chantier Pro : situation des marchés, points d'attention, sommes à payer / à réclamer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from app.models.chantier import STATUS_DONE, STATUS_PAID, STATUS_RUNNING
from app.services import chantier_service as cs, labor_service as ls, rental_service as rs, subcontract_service as ss

UPCOMING_DAYS = 30


@dataclass
class Dashboard:
    running: int = 0
    contract_total: float = 0.0
    received: float = 0.0
    receivable: float = 0.0
    spent: float = 0.0
    margin: float = 0.0
    cash: float = 0.0
    supplier_debt: float = 0.0
    month_received: float = 0.0
    month_paid: float = 0.0
    losing: int = 0
    watch: List[tuple] = field(default_factory=list)          # (chantier, [alertes])
    retention_to_claim: float = 0.0
    retention_items: List[tuple] = field(default_factory=list)  # (chantier, montant)
    upcoming: List[tuple] = field(default_factory=list)       # (chantier, libellé, montant restant, échéance)
    sub_to_pay: float = 0.0
    sub_retention_held: float = 0.0
    sub_late: List[tuple] = field(default_factory=list)       # (chantier, sous-traitant, travail)
    payroll_due: float = 0.0
    rentals_overdue: List[tuple] = field(default_factory=list)  # (client, jours de retard)
    rentals_today: List[str] = field(default_factory=list)


def build(now: Optional[datetime] = None) -> Dashboard:
    now = now or datetime.now()
    d = Dashboard()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    g_all = cs.global_result()
    g_month = cs.global_result(month_start, None)
    d.receivable, d.supplier_debt = g_all.receivable, g_all.supplier_debt
    d.month_received, d.month_paid = g_month.received, g_month.spent_paid + g_month.overheads
    d.cash = g_all.net_cash
    markets = [s for s in cs.list_summaries() if s.status in (STATUS_RUNNING, STATUS_DONE, STATUS_PAID, "litige")]
    d.running = sum(1 for s in markets if s.status == STATUS_RUNNING)
    d.contract_total = sum(s.contract for s in markets)
    d.received = sum(s.received for s in markets)
    d.spent = sum(s.spent for s in markets)
    d.margin = sum(s.margin for s in markets)
    d.losing = g_all.losing
    for s in markets:
        if s.alerts and s.status == STATUS_RUNNING:
            d.watch.append((f"{s.number} — {s.name}", list(s.alerts)))
        if s.status in (STATUS_DONE, STATUS_PAID) and s.retention_held > 0:
            d.retention_to_claim += s.retention_held
            d.retention_items.append((f"{s.number} — {s.name}", s.retention_held))
        for label, planned, cumulative, due in s.planned_vs_received:
            if due and now <= due <= now + timedelta(days=UPCOMING_DAYS) and s.received < cumulative:
                d.upcoming.append((f"{s.number} — {s.name}", label, min(planned, cumulative - s.received), due))
    d.upcoming.sort(key=lambda x: x[3])
    subs = [x for x in ss.list_subcontracts() if x.status != "annule"]
    d.sub_to_pay = sum(x.payable_now for x in subs)
    d.sub_retention_held = sum(x.retention_held for x in subs)
    d.sub_late = [(x.chantier, x.subcontractor, x.label) for x in subs if x.late]
    d.payroll_due = sum(l.net for l in ls.payroll_preview())
    a = rs.alerts()
    d.rentals_overdue = [(x.client, x.days_late) for x in a["overdue"]]
    d.rentals_today = [x.client for x in a["today"]]
    return d
