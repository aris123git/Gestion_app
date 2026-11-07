"""Location de matériel : parc, disponibilité, contrats, retour (retard, dégâts, caution), alertes."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.rental import RENTAL_OUT, RENTAL_RETURNED, Rental, RentalItem, RentalLine
from app.services import settings_service
from app.services.chantier_service import _next
from app.utils.helpers import to_float

COUNTER_KEY = "rental_counter"
LATE_MULTIPLIER_KEY = "rental_late_multiplier"   # pénalité de retard = tarif journalier × coefficient (défaut 1)
EPS = 0.0005


def _f(v) -> float:
    return float(v or 0)


def late_multiplier() -> float:
    try:
        return max(0.0, float(settings_service.get_setting(LATE_MULTIPLIER_KEY, "1") or 1))
    except ValueError:
        return 1.0


# --- parc ---------------------------------------------------------------------------------
def save_item(*, item_id: Optional[int] = None, name: str, category: str = "", quantity: int = 1, rate_day: float = 0.0,
              rate_week: float = 0.0, deposit: float = 0.0, condition: str = "Bon état", service_every_days: int = 0,
              notes: str = "", active: bool = True) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Donnez un nom au matériel.")
    if int(quantity) < 1:
        raise ValueError("La quantité doit être d'au moins 1.")
    with session_scope() as session:
        dup = session.scalar(select(RentalItem).where(func.lower(RentalItem.name) == name.lower()))
        if dup is not None and dup.id != item_id:
            raise ValueError("Ce matériel existe déjà dans le parc.")
        item = session.get(RentalItem, item_id) if item_id else RentalItem()
        if item is None:
            raise ValueError("Matériel introuvable.")
        item.name, item.category, item.quantity = name, (category or "").strip(), int(quantity)
        item.rate_day, item.rate_week, item.deposit = max(0.0, to_float(rate_day)), max(0.0, to_float(rate_week)), max(0.0, to_float(deposit))
        item.condition, item.service_every_days = condition or "Bon état", max(0, int(service_every_days))
        item.notes, item.active = (notes or "").strip(), bool(active)
        session.add(item)
        session.flush()
        return item.id


def delete_item(item_id: int) -> None:
    with session_scope() as session:
        if session.scalar(select(func.count()).select_from(RentalLine).where(RentalLine.item_id == item_id)):
            raise ValueError("Ce matériel a déjà été loué : désactivez-le plutôt que de le supprimer.")
        item = session.get(RentalItem, item_id)
        if item is not None:
            session.delete(item)


def record_repair(item_id: int, cost: float, condition: str = "Bon état") -> None:
    """Réparation / révision : cumule le coût et remet le compteur d'entretien à zéro."""
    with session_scope() as session:
        item = session.get(RentalItem, item_id)
        if item is None:
            raise ValueError("Matériel introuvable.")
        item.repair_cost = _f(item.repair_cost) + max(0.0, to_float(cost))
        item.days_since_service = 0
        item.condition = condition or "Bon état"


@dataclass
class ItemRow:
    id: int
    name: str
    category: str
    quantity: int
    out: int
    available: int
    rate_day: float
    rate_week: float
    deposit: float
    condition: str
    repair_cost: float
    needs_service: bool
    active: bool


def _out_map(session, exclude_rental: Optional[int] = None) -> dict:
    q = (select(RentalLine.item_id, func.coalesce(func.sum(RentalLine.quantity), 0))
         .join(Rental, Rental.id == RentalLine.rental_id).where(Rental.status == RENTAL_OUT).group_by(RentalLine.item_id))
    if exclude_rental:
        q = q.where(Rental.id != exclude_rental)
    return {i: int(n) for i, n in session.execute(q)}


def booked_between(session, item_id: int, start: datetime, end: datetime, exclude_rental: Optional[int] = None) -> int:
    """Quantité déjà louée qui chevauche la période [start, end[.

    Une location non rendue dont la date de retour est passée occupe encore le matériel jusqu'à son retour réel.
    """
    now = datetime.now()
    total = 0
    q = (select(Rental, RentalLine.quantity).join(RentalLine, RentalLine.rental_id == Rental.id)
         .where(RentalLine.item_id == item_id, Rental.status == RENTAL_OUT))
    if exclude_rental:
        q = q.where(Rental.id != exclude_rental)
    for rental, qty in session.execute(q):
        busy_until = max(rental.due_date, now)
        if rental.start_date < end and busy_until > start:
            total += int(qty)
    return total


def available_between(item_id: int, start: datetime, end: datetime) -> int:
    with session_scope() as session:
        item = session.get(RentalItem, item_id)
        return max(0, item.quantity - booked_between(session, item_id, start, end)) if item else 0


def _booked(session, start: datetime, end: datetime, exclude_rental: Optional[int] = None) -> dict:
    """Quantités déjà réservées par article sur la période [start, end] (locations non rendues qui se chevauchent).

    Une location non rendue et déjà en retard garde son matériel : sa fin effective est « maintenant ».
    """
    now = datetime.now()
    q = (select(Rental.id, Rental.start_date, Rental.due_date, RentalLine.item_id, RentalLine.quantity)
         .join(RentalLine, RentalLine.rental_id == Rental.id).where(Rental.status == RENTAL_OUT))
    booked: dict = {}
    for rid, r_start, r_due, item_id, qty in session.execute(q):
        if exclude_rental and rid == exclude_rental:
            continue
        r_end = max(r_due, now)
        if r_start < end and r_end > start:
            booked[item_id] = booked.get(item_id, 0) + int(qty)
    return booked


def list_items(include_inactive: bool = False) -> List[ItemRow]:
    with session_scope() as session:
        out = _out_map(session)
        q = select(RentalItem).order_by(RentalItem.name)
        if not include_inactive:
            q = q.where(RentalItem.active.is_(True))
        rows = []
        for i in session.scalars(q):
            n_out = out.get(i.id, 0)
            rows.append(ItemRow(
                i.id, i.name, i.category, i.quantity, n_out, max(0, i.quantity - n_out), _f(i.rate_day), _f(i.rate_week), _f(i.deposit),
                i.condition, _f(i.repair_cost), bool(i.service_every_days and i.days_since_service >= i.service_every_days), i.active))
        return rows


# --- calculs -----------------------------------------------------------------------------------
def billed_days(start: datetime, end: datetime) -> int:
    """Nombre de jours facturés : toute journée entamée compte, minimum 1."""
    return max(1, math.ceil((end - start).total_seconds() / 86400 - 1e-9))


def day_total(lines) -> float:
    return sum(_f(l.rate_day) * int(l.quantity) for l in lines)


@dataclass
class LineInput:
    item_id: int
    quantity: int = 1
    rate_day: Optional[float] = None    # défaut : tarif du parc


def create_rental(*, client_label: str, due_date: datetime, lines: List[LineInput], start_date: Optional[datetime] = None,
                  client_id: Optional[int] = None, phone: str = "", id_document: str = "", deposit: Optional[float] = None,
                  paid: float = 0.0, chantier_id: Optional[int] = None, out_condition: str = "", notes: str = "",
                  user_id: Optional[int] = None) -> int:
    client_label = (client_label or "").strip()
    if not client_label and not chantier_id:
        raise ValueError("Indiquez le client (ou le chantier pour un usage interne).")
    start = start_date or datetime.now()
    if due_date <= start:
        raise ValueError("La date de retour doit être après le départ.")
    if not lines:
        raise ValueError("Ajoutez au moins un matériel.")
    with session_scope() as session:
        rental = Rental(number=_next(COUNTER_KEY, "LOC", session, Rental.number), client_id=client_id, client_label=client_label,
                        phone=(phone or "").strip(), id_document=(id_document or "").strip(), start_date=start, due_date=due_date,
                        chantier_id=chantier_id, out_condition=(out_condition or "").strip(), notes=(notes or "").strip(),
                        paid=max(0.0, to_float(paid)), user_id=user_id)
        default_deposit = 0.0
        wanted: dict = {}
        for li in lines:
            qty = int(li.quantity)
            if qty < 1:
                raise ValueError("Quantité invalide.")
            item = session.get(RentalItem, li.item_id)
            if item is None or not item.active:
                raise ValueError("Matériel introuvable ou désactivé.")
            wanted[item.id] = wanted.get(item.id, 0) + qty
            free = item.quantity - booked_between(session, item.id, start, due_date)
            if wanted[item.id] > free:
                raise ValueError(f"« {item.name} » : seulement {max(0, free)} disponible(s) du {start:%d/%m/%Y} au {due_date:%d/%m/%Y}.")
            rate = _f(item.rate_day) if li.rate_day is None else max(0.0, to_float(li.rate_day))
            rental.lines.append(RentalLine(item_id=item.id, label=item.name, quantity=qty, rate_day=rate))
            default_deposit += _f(item.deposit) * qty
        rental.deposit = default_deposit if deposit is None else max(0.0, to_float(deposit))
        session.add(rental)
        session.flush()
        return rental.id


def update_due_date(rental_id: int, due_date: datetime) -> None:
    """Prolongation de la location (refusée si le matériel est réservé par une autre location sur les nouveaux jours)."""
    with session_scope() as session:
        r = _load(session, rental_id) if session.get(Rental, rental_id) else None
        if r is None or r.status != RENTAL_OUT:
            raise ValueError("Location introuvable ou déjà rendue.")
        if due_date <= r.start_date:
            raise ValueError("La date de retour doit être après le départ.")
        for line in r.lines:
            item = session.get(RentalItem, line.item_id)
            if booked_between(session, line.item_id, r.due_date, due_date, exclude_rental=r.id) + int(line.quantity) > item.quantity:
                raise ValueError(f"« {item.name} » est déjà réservé après le {r.due_date:%d/%m/%Y} : prolongation impossible.")
        r.due_date = due_date


def add_payment(rental_id: int, amount: float) -> None:
    value = to_float(amount)
    if value <= 0:
        raise ValueError("Le montant doit être supérieur à zéro.")
    with session_scope() as session:
        r = session.get(Rental, rental_id)
        if r is None:
            raise ValueError("Location introuvable.")
        r.paid = _f(r.paid) + value


@dataclass
class RentalSummary:
    id: int
    number: str
    client: str
    phone: str
    status: str
    start_date: datetime
    due_date: datetime
    returned_at: Optional[datetime]
    items: str
    days_planned: int = 0
    days_late: int = 0
    base: float = 0.0
    late_fee: float = 0.0
    damage_fee: float = 0.0
    total: float = 0.0
    paid: float = 0.0
    balance: float = 0.0           # reste dû sur le loyer (avant caution)
    deposit: float = 0.0
    deposit_refunded: float = 0.0
    overdue: bool = False
    due_today: bool = False
    alerts: List[str] = field(default_factory=list)


def _summarize(r: Rental, now: Optional[datetime] = None) -> RentalSummary:
    now = now or datetime.now()
    per_day = day_total(r.lines)
    planned = billed_days(r.start_date, r.due_date)
    base = per_day * planned
    end = r.returned_at or now
    late_days = 0
    if end > r.due_date + timedelta(hours=0):
        late_days = max(0, math.ceil((end - r.due_date).total_seconds() / 86400 - 1e-9))
    returned = r.status == RENTAL_RETURNED
    late_fee = _f(r.late_fee) if returned else round(per_day * late_days * late_multiplier(), 3)
    damage = _f(r.damage_fee)
    total = base + late_fee + damage
    s = RentalSummary(
        id=r.id, number=r.number, client=r.client_label, phone=r.phone, status=r.status, start_date=r.start_date, due_date=r.due_date,
        returned_at=r.returned_at, items=", ".join(f"{l.quantity}× {l.label}" for l in r.lines), days_planned=planned, days_late=late_days,
        base=base, late_fee=late_fee, damage_fee=damage, total=total, paid=_f(r.paid), balance=max(0.0, total - _f(r.paid)),
        deposit=_f(r.deposit), deposit_refunded=_f(r.deposit_refunded),
    )
    if not returned:
        s.overdue = now > r.due_date
        s.due_today = (not s.overdue) and r.due_date.date() == now.date()
        if s.overdue:
            s.alerts.append(f"En retard de {late_days} jour(s) : pénalité en cours {late_fee:g}.")
        elif s.due_today:
            s.alerts.append("À rendre aujourd'hui.")
    return s


def _load(session, rental_id: int) -> Rental:
    r = session.execute(select(Rental).options(joinedload(Rental.lines)).where(Rental.id == rental_id)).unique().scalar_one_or_none()
    if r is None:
        raise ValueError("Location introuvable.")
    return r


def summary(rental_id: int) -> RentalSummary:
    with session_scope() as session:
        return _summarize(_load(session, rental_id))


def list_rentals(status: Optional[str] = None, search: str = "") -> List[RentalSummary]:
    with session_scope() as session:
        q = select(Rental).options(joinedload(Rental.lines)).order_by(Rental.id.desc())
        if status:
            q = q.where(Rental.status == status)
        rows = session.execute(q).unique().scalars().all()
        needle = (search or "").strip().casefold()
        if needle:
            rows = [r for r in rows if needle in f"{r.number} {r.client_label} {r.phone} {' '.join(l.label for l in r.lines)}".casefold()]
        return [_summarize(r) for r in rows]


def alerts() -> dict:
    """Compteurs pour les rappels : retards, retours du jour."""
    rows = [s for s in list_rentals(RENTAL_OUT)]
    return {"overdue": [s for s in rows if s.overdue], "today": [s for s in rows if s.due_today]}


def return_rental(rental_id: int, *, returned_at: Optional[datetime] = None, damage_fee: float = 0.0, return_condition: str = "",
                  refund_deposit: bool = True) -> RentalSummary:
    """Enregistre le retour : fige pénalité et dégâts, impute la caution sur le dû, rend le surplus."""
    with session_scope() as session:
        r = _load(session, rental_id)
        if r.status == RENTAL_RETURNED:
            raise ValueError("Cette location est déjà rendue.")
        when = returned_at or datetime.now()
        if when < r.start_date:
            raise ValueError("Le retour ne peut pas précéder le départ.")
        per_day = day_total(r.lines)
        late_days = max(0, math.ceil((when - r.due_date).total_seconds() / 86400 - 1e-9)) if when > r.due_date else 0
        r.returned_at, r.status = when, RENTAL_RETURNED
        r.late_fee = round(per_day * late_days * late_multiplier(), 3)
        r.damage_fee = max(0.0, to_float(damage_fee))
        r.return_condition = (return_condition or "").strip()
        total = per_day * billed_days(r.start_date, r.due_date) + _f(r.late_fee) + _f(r.damage_fee)
        owed = max(0.0, total - _f(r.paid))
        deposit = _f(r.deposit)
        applied = min(deposit, owed)
        r.paid = _f(r.paid) + applied                       # la caution règle d'abord ce qui est dû
        r.deposit_refunded = (deposit - applied) if refund_deposit else 0.0
        # compteurs d'entretien du matériel
        days_used = billed_days(r.start_date, when)
        for line in r.lines:
            item = session.get(RentalItem, line.item_id)
            if item is not None:
                item.days_since_service = int(item.days_since_service or 0) + days_used
        session.flush()
        return _summarize(r, now=when)


def delete_rental(rental_id: int) -> None:
    with session_scope() as session:
        r = session.get(Rental, rental_id)
        if r is None:
            return
        if r.status == RENTAL_RETURNED or _f(r.paid):
            raise ValueError("Une location rendue ou encaissée ne peut pas être supprimée.")
        session.delete(r)


def revenue(start: Optional[datetime] = None, end: Optional[datetime] = None) -> float:
    """Loyers encaissés sur les locations dont le départ tombe dans la période."""
    with session_scope() as session:
        q = select(func.coalesce(func.sum(Rental.paid), 0))
        if start:
            q = q.where(Rental.start_date >= start)
        if end:
            q = q.where(Rental.start_date < end)
        return _f(session.scalar(q))
