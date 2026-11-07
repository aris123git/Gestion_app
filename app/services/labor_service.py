"""Main-d'œuvre : ouvriers, pointage par chantier, avances, paie (qui devient une dépense du chantier)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.chantier import MARKET_STATUSES, Chantier
from app.models.labor import Worker, WorkerAdvance, WorkerDay
from app.services import chantier_service as cs
from app.utils.helpers import to_float

CATEGORY = "Main-d'œuvre"


def _f(v) -> float:
    return float(v or 0)


def save_worker(*, worker_id: Optional[int] = None, name: str, trade: str = "", phone: str = "", daily_rate: float = 0.0,
                active: bool = True) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Donnez le nom de l'ouvrier.")
    with session_scope() as session:
        dup = session.scalar(select(Worker).where(func.lower(Worker.name) == name.lower()))
        if dup is not None and dup.id != worker_id:
            raise ValueError("Cet ouvrier existe déjà.")
        w = session.get(Worker, worker_id) if worker_id else Worker()
        if w is None:
            raise ValueError("Ouvrier introuvable.")
        w.name, w.trade, w.phone = name, (trade or "").strip(), (phone or "").strip()
        w.daily_rate, w.active = max(0.0, to_float(daily_rate)), bool(active)
        session.add(w)
        session.flush()
        return w.id


def list_workers(include_inactive: bool = False) -> List[Worker]:
    with session_scope() as session:
        q = select(Worker).order_by(Worker.name)
        if not include_inactive:
            q = q.where(Worker.active.is_(True))
        rows = list(session.scalars(q))
        session.expunge_all()
        return rows


def delete_worker(worker_id: int) -> None:
    with session_scope() as session:
        if session.scalar(select(func.count()).select_from(WorkerDay).where(WorkerDay.worker_id == worker_id)):
            raise ValueError("Cet ouvrier a des pointages : désactivez-le plutôt que de le supprimer.")
        w = session.get(Worker, worker_id)
        if w is not None:
            session.delete(w)


def clock_in(worker_id: int, chantier_id: int, *, date: Optional[datetime] = None, days: float = 1.0, notes: str = "") -> int:
    days = to_float(days)
    if not 0 < days <= 3:
        raise ValueError("Les jours pointés doivent être entre 0 et 3 (ex. 0,5 ou 1).")
    day = (date or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as session:
        w = session.get(Worker, worker_id)
        c = session.get(Chantier, chantier_id)
        if w is None or c is None:
            raise ValueError("Ouvrier ou chantier introuvable.")
        if c.status not in MARKET_STATUSES:
            raise ValueError("Le pointage se fait sur un marché en cours (convertissez d'abord le devis).")
        total_that_day = _f(session.scalar(select(func.coalesce(func.sum(WorkerDay.days), 0)).where(
            WorkerDay.worker_id == worker_id, WorkerDay.date == day)))
        if total_that_day + days > 1 + 1e-9:
            raise ValueError(f"{w.name} est déjà pointé {total_that_day:g} jour ce jour-là (maximum 1 jour par jour).")
        row = WorkerDay(worker_id=worker_id, chantier_id=chantier_id, date=day, days=days, rate=_f(w.daily_rate), notes=(notes or "").strip())
        session.add(row)
        session.flush()
        return row.id


def delete_day(day_id: int) -> None:
    with session_scope() as session:
        row = session.get(WorkerDay, day_id)
        if row is None:
            return
        if row.paid:
            raise ValueError("Ce pointage est déjà payé : il ne peut plus être supprimé.")
        session.delete(row)


@dataclass
class DayRow:
    id: int
    worker: str
    chantier: str
    date: datetime
    days: float
    rate: float
    amount: float
    paid: bool


def list_days(chantier_id: Optional[int] = None, worker_id: Optional[int] = None, unpaid_only: bool = False,
              start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[DayRow]:
    with session_scope() as session:
        q = (select(WorkerDay, Worker.name, Chantier.name).join(Worker, Worker.id == WorkerDay.worker_id)
             .join(Chantier, Chantier.id == WorkerDay.chantier_id).order_by(WorkerDay.date.desc(), WorkerDay.id.desc()))
        if chantier_id:
            q = q.where(WorkerDay.chantier_id == chantier_id)
        if worker_id:
            q = q.where(WorkerDay.worker_id == worker_id)
        if unpaid_only:
            q = q.where(WorkerDay.paid.is_(False))
        if start:
            q = q.where(WorkerDay.date >= start)
        if end:
            q = q.where(WorkerDay.date < end)
        return [DayRow(d.id, w, c, d.date, _f(d.days), _f(d.rate), round(_f(d.days) * _f(d.rate), 3), bool(d.paid)) for d, w, c in session.execute(q)]


# --- avances -----------------------------------------------------------------------------
def add_advance(worker_id: int, amount: float, *, date: Optional[datetime] = None, notes: str = "") -> int:
    value = to_float(amount)
    if value <= 0:
        raise ValueError("Le montant de l'avance doit être supérieur à zéro.")
    with session_scope() as session:
        if session.get(Worker, worker_id) is None:
            raise ValueError("Ouvrier introuvable.")
        row = WorkerAdvance(worker_id=worker_id, amount=value, date=date or datetime.now(), notes=(notes or "").strip())
        session.add(row)
        session.flush()
        return row.id


def advances_due(worker_id: int) -> float:
    with session_scope() as session:
        return _f(session.scalar(select(func.coalesce(func.sum(WorkerAdvance.amount), 0)).where(
            WorkerAdvance.worker_id == worker_id, WorkerAdvance.deducted.is_(False))))


# --- paie -----------------------------------------------------------------------------------
@dataclass
class PayrollLine:
    worker_id: int
    worker: str
    days: float
    gross: float
    advances: float
    net: float


def payroll_preview(start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[PayrollLine]:
    """Par ouvrier : jours non payés, brut, avances à déduire, net à verser."""
    with session_scope() as session:
        q = select(WorkerDay.worker_id, Worker.name, func.sum(WorkerDay.days), func.sum(WorkerDay.days * WorkerDay.rate)).join(
            Worker, Worker.id == WorkerDay.worker_id).where(WorkerDay.paid.is_(False)).group_by(WorkerDay.worker_id, Worker.name)
        if start:
            q = q.where(WorkerDay.date >= start)
        if end:
            q = q.where(WorkerDay.date < end)
        rows = [(i, n, _f(d), _f(g)) for i, n, d, g in session.execute(q)]
    lines = []
    for wid, name, days, gross in rows:
        adv = advances_due(wid)
        ded = min(adv, gross)
        lines.append(PayrollLine(wid, name, days, gross, ded, gross - ded))
    return sorted(lines, key=lambda l: l.worker.casefold())


def pay_worker(worker_id: int, *, start: Optional[datetime] = None, end: Optional[datetime] = None, user_id: Optional[int] = None) -> List[int]:
    """Paie un ouvrier : une dépense « Main-d'œuvre » par chantier (coût brut), avances déduites du net versé.

    Le coût brut va au chantier ; l'avance a déjà été versée en espèces plus tôt, elle n'est donc pas redécomptée.
    """
    with session_scope() as session:
        q = select(WorkerDay).where(WorkerDay.worker_id == worker_id, WorkerDay.paid.is_(False))
        if start:
            q = q.where(WorkerDay.date >= start)
        if end:
            q = q.where(WorkerDay.date < end)
        days = list(session.scalars(q))
        worker = session.get(Worker, worker_id)
        if worker is None or not days:
            raise ValueError("Rien à payer pour cet ouvrier sur la période.")
        per_chantier: dict = {}
        for d in days:
            bucket = per_chantier.setdefault(d.chantier_id, [0.0, 0.0])
            bucket[0] += _f(d.days)
            bucket[1] += _f(d.days) * _f(d.rate)
        name = worker.name
        for d in days:
            d.paid = True
        gross_total = sum(b[1] for b in per_chantier.values())
        advances = list(session.scalars(select(WorkerAdvance).where(WorkerAdvance.worker_id == worker_id, WorkerAdvance.deducted.is_(False))
                                        .order_by(WorkerAdvance.date, WorkerAdvance.id)))
        remaining = gross_total
        for a in advances:
            if _f(a.amount) <= remaining + 1e-9:        # on ne déduit que des avances entières
                a.deducted = True
                remaining -= _f(a.amount)
        deducted = gross_total - remaining
    created = []
    for chantier_id, (nb_days, gross) in per_chantier.items():
        if gross <= 0:
            continue
        note = f"Paie {name} — {nb_days:g} j" + (f" (avances déduites : {deducted:g})" if deducted else "")
        created.append(cs.add_expense(chantier_id, category=CATEGORY, label=name, amount=round(gross, 3), worker=name, days=nb_days,
                                      daily_rate=round(gross / nb_days, 3) if nb_days else 0.0, notes=note, user_id=user_id))
    return created
