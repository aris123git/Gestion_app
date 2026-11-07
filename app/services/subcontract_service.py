"""Sous-traitance : contrats par chantier, paiements (chaque paiement devient une dépense « Sous-traitant » du chantier)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.chantier import MARKET_STATUSES, Chantier
from app.models.subcontract import (
    RETENTION_RELEASE, SUB_CANCELLED, SUB_DONE, SUB_RUNNING, SUB_STATUS_LABELS, Subcontract, SubcontractPayment, Subcontractor,
)
from app.services import chantier_service as cs
from app.utils.helpers import to_float

COUNTER_KEY = "subcontract_counter"
CATEGORY = "Sous-traitant"
EPS = 0.0005


def _f(v) -> float:
    return float(v or 0)


# --- sous-traitants ---------------------------------------------------------------------------
def save_subcontractor(*, subcontractor_id: Optional[int] = None, name: str, trade: str = "", phone: str = "", address: str = "",
                       tax_id: str = "", notes: str = "", active: bool = True) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Donnez le nom du sous-traitant.")
    with session_scope() as session:
        dup = session.scalar(select(Subcontractor).where(func.lower(Subcontractor.name) == name.lower()))
        if dup is not None and dup.id != subcontractor_id:
            raise ValueError("Ce sous-traitant existe déjà.")
        row = session.get(Subcontractor, subcontractor_id) if subcontractor_id else Subcontractor()
        if row is None:
            raise ValueError("Sous-traitant introuvable.")
        row.name, row.trade, row.phone = name, (trade or "").strip(), (phone or "").strip()
        row.address, row.tax_id, row.notes, row.active = (address or "").strip(), (tax_id or "").strip(), (notes or "").strip(), bool(active)
        session.add(row)
        session.flush()
        return row.id


def list_subcontractors(include_inactive: bool = False) -> List[Subcontractor]:
    with session_scope() as session:
        q = select(Subcontractor).order_by(Subcontractor.name)
        if not include_inactive:
            q = q.where(Subcontractor.active.is_(True))
        rows = list(session.scalars(q))
        session.expunge_all()
        return rows


def delete_subcontractor(subcontractor_id: int) -> None:
    with session_scope() as session:
        if session.scalar(select(func.count()).select_from(Subcontract).where(Subcontract.subcontractor_id == subcontractor_id)):
            raise ValueError("Ce sous-traitant a des contrats : désactivez-le plutôt que de le supprimer.")
        row = session.get(Subcontractor, subcontractor_id)
        if row is not None:
            session.delete(row)


# --- contrats ----------------------------------------------------------------------------------
def create_subcontract(chantier_id: int, subcontractor_id: int, label: str, amount: float, *, retention_pct: float = 0.0,
                       start_date: Optional[datetime] = None, end_planned: Optional[datetime] = None, notes: str = "",
                       user_id: Optional[int] = None) -> int:
    label = (label or "").strip()
    if not label:
        raise ValueError("Décrivez le travail confié (lot ou tâche).")
    value = to_float(amount)
    if value <= 0:
        raise ValueError("Le montant du contrat doit être supérieur à zéro.")
    pct = to_float(retention_pct)
    if not 0 <= pct <= 30:
        raise ValueError("La retenue de garantie doit être comprise entre 0 et 30 %.")
    with session_scope() as session:
        chantier = session.get(Chantier, chantier_id)
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        if chantier.status not in MARKET_STATUSES:
            raise ValueError("Le sous-traitant se rattache à un marché en cours (convertissez d'abord le devis).")
        sub = session.get(Subcontractor, subcontractor_id)
        if sub is None or not sub.active:
            raise ValueError("Sous-traitant introuvable ou désactivé.")
        row = Subcontract(number=cs._next(COUNTER_KEY, "ST", session, Subcontract.number), chantier_id=chantier_id,
                          subcontractor_id=subcontractor_id, label=label, amount=value, retention_pct=pct, start_date=start_date,
                          end_planned=end_planned, notes=(notes or "").strip(), user_id=user_id)
        session.add(row)
        session.flush()
        return row.id


def set_status(subcontract_id: int, status: str) -> None:
    if status not in SUB_STATUS_LABELS:
        raise ValueError("Statut inconnu.")
    with session_scope() as session:
        row = session.get(Subcontract, subcontract_id)
        if row is None:
            raise ValueError("Contrat introuvable.")
        row.status = status


def delete_subcontract(subcontract_id: int) -> None:
    with session_scope() as session:
        row = session.execute(select(Subcontract).options(joinedload(Subcontract.payments)).where(Subcontract.id == subcontract_id)).unique().scalar_one_or_none()
        if row is None:
            return
        if row.payments:
            raise ValueError("Ce contrat a des paiements : annulez-le plutôt que de le supprimer.")
        session.delete(row)


@dataclass
class SubSummary:
    id: int
    number: str
    chantier_id: int
    chantier: str
    subcontractor: str
    label: str
    status: str
    amount: float
    retention_pct: float
    retention: float            # montant retenu jusqu'à réception
    paid: float                 # tout ce qui a été versé (retenue libérée incluse)
    paid_work: float            # versé hors libération de retenue
    payable_now: float          # reste à payer sans toucher à la retenue
    retention_held: float       # retenue encore détenue
    end_planned: Optional[datetime] = None
    late: bool = False
    alerts: List[str] = field(default_factory=list)


def _summarize(sc: Subcontract, chantier_name: str, sub_name: str) -> SubSummary:
    amount = _f(sc.amount)
    retention = round(amount * _f(sc.retention_pct) / 100, 3)
    released = sum(_f(p.amount) for p in sc.payments if p.kind == RETENTION_RELEASE)
    paid_work = sum(_f(p.amount) for p in sc.payments if p.kind != RETENTION_RELEASE)
    s = SubSummary(id=sc.id, number=sc.number, chantier_id=sc.chantier_id, chantier=chantier_name, subcontractor=sub_name, label=sc.label,
                   status=sc.status, amount=amount, retention_pct=_f(sc.retention_pct), retention=retention, paid=paid_work + released,
                   paid_work=paid_work, payable_now=max(0.0, amount - retention - paid_work), retention_held=max(0.0, retention - released),
                   end_planned=sc.end_planned)
    if sc.status == SUB_RUNNING and sc.end_planned and datetime.now() > sc.end_planned:
        s.late = True
        s.alerts.append(f"Échéance dépassée le {sc.end_planned:%d/%m/%Y}.")
    if sc.status == SUB_DONE and s.retention_held > EPS:
        s.alerts.append(f"Travaux réceptionnés : retenue de {s.retention_held:g} à libérer.")
    return s


def list_subcontracts(chantier_id: Optional[int] = None, subcontractor_id: Optional[int] = None, status: Optional[str] = None) -> List[SubSummary]:
    with session_scope() as session:
        q = (select(Subcontract, Chantier.name, Subcontractor.name).options(joinedload(Subcontract.payments))
             .join(Chantier, Chantier.id == Subcontract.chantier_id).join(Subcontractor, Subcontractor.id == Subcontract.subcontractor_id)
             .order_by(Subcontract.id.desc()))
        if chantier_id:
            q = q.where(Subcontract.chantier_id == chantier_id)
        if subcontractor_id:
            q = q.where(Subcontract.subcontractor_id == subcontractor_id)
        if status:
            q = q.where(Subcontract.status == status)
        return [_summarize(sc, c, n) for sc, c, n in session.execute(q).unique()]


def summary(subcontract_id: int) -> SubSummary:
    rows = [s for s in list_subcontracts() if s.id == subcontract_id]
    if not rows:
        raise ValueError("Contrat introuvable.")
    return rows[0]


def chantier_totals(chantier_id: int) -> dict:
    rows = [s for s in list_subcontracts(chantier_id) if s.status != SUB_CANCELLED]
    return {"engaged": sum(s.amount for s in rows), "paid": sum(s.paid for s in rows),
            "to_pay": sum(s.payable_now for s in rows), "retention_held": sum(s.retention_held for s in rows), "count": len(rows)}


# --- paiements -----------------------------------------------------------------------------------
def add_payment(subcontract_id: int, amount: float, *, kind: str = "Acompte", reference: str = "", date: Optional[datetime] = None,
                notes: str = "", user_id: Optional[int] = None) -> int:
    value = to_float(amount)
    if value <= 0:
        raise ValueError("Le montant doit être supérieur à zéro.")
    s = summary(subcontract_id)
    if s.status == SUB_CANCELLED:
        raise ValueError("Ce contrat est annulé.")
    if kind == RETENTION_RELEASE:
        if s.status != SUB_DONE:
            raise ValueError("La retenue ne se libère qu'après réception des travaux (passez le contrat à « Terminé »).")
        if value > s.retention_held + EPS:
            raise ValueError(f"Retenue disponible : {s.retention_held:g} seulement.")
    else:
        if value > s.payable_now + EPS:
            raise ValueError(f"Reste à payer (hors retenue) : {s.payable_now:g}. Le surplus dépasse le contrat.")
    when = date or datetime.now()
    label = f"{s.subcontractor} — {s.label} ({kind})"
    expense_id = cs.add_expense(s.chantier_id, category=CATEGORY, label=label, amount=value, supplier=s.subcontractor, date=when,
                                notes=f"{s.number} · {kind}" + (f" · réf. {reference}" if reference else ""), user_id=user_id)
    with session_scope() as session:
        row = SubcontractPayment(subcontract_id=subcontract_id, date=when, kind=kind, amount=value, reference=(reference or "").strip(),
                                 expense_id=expense_id, notes=(notes or "").strip())
        session.add(row)
        session.flush()
        return row.id


def list_payments(subcontract_id: int) -> List[SubcontractPayment]:
    with session_scope() as session:
        rows = list(session.scalars(select(SubcontractPayment).where(SubcontractPayment.subcontract_id == subcontract_id)
                                    .order_by(SubcontractPayment.date, SubcontractPayment.id)))
        session.expunge_all()
        return rows


def delete_payment(payment_id: int) -> None:
    with session_scope() as session:
        row = session.get(SubcontractPayment, payment_id)
        if row is None:
            return
        expense_id = row.expense_id
        session.delete(row)
    if expense_id:
        cs.delete_expense(expense_id)
