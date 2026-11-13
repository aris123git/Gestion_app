"""Contrôle gaz : stock de bouteilles, ventes détaillants (cahier du jour), livraisons et comptes des grossistes, pertes.

Tout est séparé de la caisse du logiciel. Le stock d'un produit = somme signée de ses mouvements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.gas import (
    FORMULA_COMPLET, FORMULA_CONSIGNE, FORMULA_RECHARGE, FORMULAS, MOVE_ADJUST, MOVE_DELIVERY, MOVE_ENTRY, MOVE_LOSS,
    MOVE_SALE, MOVE_TRANSFER, TRIP_CLOSED, TRIP_OPEN, GasDelivery, GasDeliveryItem, GasEmptiesReturn, GasLine, GasMovement, GasPayment,
    GasTrip, GasWholesaler,
)
from app.services import settings_service

SETTING_ENABLED = "gas_enabled"
SETTING_INCLUDE = "gas_include_in_totals"


class GasError(ValueError):
    pass


def _f(v) -> float:
    return float(v or 0)


def enabled() -> bool:
    return settings_service.get_setting(SETTING_ENABLED, "0") == "1"


def set_enabled(value: bool) -> None:
    settings_service.set_setting(SETTING_ENABLED, "1" if value else "0")


def include_in_totals() -> bool:
    return settings_service.get_setting(SETTING_INCLUDE, "0") == "1"


def set_include_in_totals(value: bool) -> None:
    settings_service.set_setting(SETTING_INCLUDE, "1" if value else "0")


def _day_bounds(day: date) -> Tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day)
    return start, start + timedelta(days=1)


# ---------------------------------------------------------------- produits
@dataclass
class LineRow:
    id: int
    name: str
    size_kg: float
    formula: str
    retail_price: float
    wholesale_price: float
    cost_price: Optional[float]
    active: bool
    stock: int = 0


def _label(size: float, formula: str) -> str:
    s = f"{size:g}".replace(".", ",")
    return f"{s} kg {FORMULAS.get(formula, formula)}"


def _where_source(q, trip_id: Optional[int]):
    """Stock du dépôt (trip_id absent) ou du camion d'un voyage."""
    return q.where(GasMovement.trip_id.is_(None) if trip_id is None else GasMovement.trip_id == trip_id)


def stock_of(session, line_id: int, before: Optional[datetime] = None, trip_id: Optional[int] = None) -> int:
    q = _where_source(select(func.coalesce(func.sum(GasMovement.qty), 0)).where(GasMovement.line_id == line_id), trip_id)
    if before is not None:
        q = q.where(GasMovement.moved_at < before)
    return int(session.execute(q).scalar() or 0)


def _row(session, ln: GasLine, trip_id: Optional[int] = None) -> LineRow:
    return LineRow(ln.id, ln.name, _f(ln.size_kg), ln.formula, _f(ln.retail_price), _f(ln.wholesale_price),
                   None if ln.cost_price is None else _f(ln.cost_price), bool(ln.active), stock_of(session, ln.id, trip_id=trip_id))


def list_lines(active_only: bool = True, trip_id: Optional[int] = None) -> List[LineRow]:
    """Produits avec leur stock : celui du dépôt, ou celui du camion si ``trip_id`` est donné."""
    with session_scope() as s:
        q = select(GasLine).order_by(GasLine.size_kg, GasLine.id)
        if active_only:
            q = q.where(GasLine.active.is_(True))
        return [_row(s, ln, trip_id) for ln in s.execute(q).scalars()]


def save_line(size_kg: float, formula: str, retail_price: float = 0, wholesale_price: float = 0,
              cost_price: Optional[float] = None, line_id: Optional[int] = None, active: bool = True) -> int:
    if formula not in FORMULAS:
        raise GasError("Formule inconnue.")
    if size_kg <= 0:
        raise GasError("La taille de la bouteille doit être positive.")
    if min(retail_price, wholesale_price) < 0 or (cost_price is not None and cost_price < 0):
        raise GasError("Les prix ne peuvent pas être négatifs.")
    with session_scope() as s:
        ln = s.get(GasLine, line_id) if line_id else None
        if ln is None:
            ln = GasLine(name=_label(size_kg, formula))
            s.add(ln)
        ln.size_kg, ln.formula, ln.name = size_kg, formula, _label(size_kg, formula)
        ln.retail_price, ln.wholesale_price, ln.cost_price, ln.active = retail_price, wholesale_price, cost_price, active
        try:
            s.flush()
        except Exception as exc:  # doublon de nom
            raise GasError("Ce produit existe déjà.") from exc
        return ln.id


def create_standard_lines() -> int:
    """6 kg et 12,5 kg × Recharge / Consigné / Complet, prix à 0 (à renseigner). Ne recrée pas l'existant."""
    made = 0
    with session_scope() as s:
        have = {(_f(ln.size_kg), ln.formula) for ln in s.execute(select(GasLine)).scalars()}
        for size in (6.0, 12.5):
            for formula in (FORMULA_RECHARGE, FORMULA_CONSIGNE, FORMULA_COMPLET):
                if (size, formula) not in have:
                    s.add(GasLine(name=_label(size, formula), size_kg=size, formula=formula))
                    made += 1
    return made


# ---------------------------------------------------------------- mouvements
def _move(s, line_id: int, kind: str, qty: int, when: Optional[datetime], unit_price: float = 0, reason: str = "",
          wholesaler_id: Optional[int] = None, delivery_id: Optional[int] = None, trip_id: Optional[int] = None) -> None:
    s.add(GasMovement(moved_at=when or datetime.now(), line_id=line_id, kind=kind, qty=qty, unit_price=unit_price,
                      reason=reason, wholesaler_id=wholesaler_id, delivery_id=delivery_id, trip_id=trip_id))


def _open_trip(s, trip_id: Optional[int]) -> None:
    if trip_id is None:
        return
    trip = s.get(GasTrip, trip_id)
    if trip is None:
        raise GasError("Voyage introuvable.")
    if trip.status != TRIP_OPEN:
        raise GasError("Ce voyage est terminé.")


def _need_stock(s, line_id: int, qty: int, trip_id: Optional[int] = None) -> None:
    ln = s.get(GasLine, line_id)
    if ln is None:
        raise GasError("Produit gaz introuvable.")
    have = stock_of(s, line_id, trip_id=trip_id)
    if have < qty:
        raise GasError(f"Stock insuffisant pour {ln.name} dans {'le camion' if trip_id else 'le dépôt'} : {have} disponible(s).")


def add_entry(line_id: int, qty: int, when: Optional[datetime] = None, reason: str = "", trip_id: Optional[int] = None) -> None:
    """Entrée de pleines en stock (dépôt) ou chargement du camion (``trip_id``)."""
    if qty <= 0:
        raise GasError("Quantité invalide.")
    with session_scope() as s:
        if s.get(GasLine, line_id) is None:
            raise GasError("Produit gaz introuvable.")
        _open_trip(s, trip_id)
        _move(s, line_id, MOVE_ENTRY, qty, when, reason=reason, trip_id=trip_id)


def adjust_stock(line_id: int, delta: int, reason: str = "", when: Optional[datetime] = None, trip_id: Optional[int] = None) -> None:
    if delta == 0:
        return
    with session_scope() as s:
        _open_trip(s, trip_id)
        if delta < 0:
            _need_stock(s, line_id, -delta, trip_id)
        _move(s, line_id, MOVE_ADJUST, delta, when, reason=reason, trip_id=trip_id)


def retail_sale(line_id: int, qty: int, unit_price: Optional[float] = None, when: Optional[datetime] = None,
                trip_id: Optional[int] = None) -> float:
    """Vente anonyme à un détaillant (aucune information client). Prix modifiable ; défaut = prix détaillant."""
    if qty <= 0:
        raise GasError("Quantité invalide.")
    with session_scope() as s:
        ln = s.get(GasLine, line_id)
        if ln is None:
            raise GasError("Produit gaz introuvable.")
        _open_trip(s, trip_id)
        _need_stock(s, line_id, qty, trip_id)
        price = _f(ln.retail_price) if unit_price is None else float(unit_price)
        if price < 0:
            raise GasError("Prix invalide.")
        _move(s, line_id, MOVE_SALE, -qty, when, unit_price=price, trip_id=trip_id)
        return qty * price


def record_loss(line_id: int, qty: int, reason: str, when: Optional[datetime] = None, trip_id: Optional[int] = None) -> None:
    """Perte (fuite, casse…) : motif libre, supportée par l'entreprise, rien n'est facturé."""
    if qty <= 0:
        raise GasError("Quantité invalide.")
    if not reason.strip():
        raise GasError("Indiquez le motif de la perte.")
    with session_scope() as s:
        _open_trip(s, trip_id)
        _need_stock(s, line_id, qty, trip_id)
        _move(s, line_id, MOVE_LOSS, -qty, when, reason=reason.strip(), trip_id=trip_id)


# ---------------------------------------------------------------- grossistes
@dataclass
class WholesalerRow:
    id: int
    name: str
    phone: str
    address: str
    notes: str
    active: bool


def save_wholesaler(name: str, phone: str = "", address: str = "", notes: str = "", wholesaler_id: Optional[int] = None,
                    active: bool = True) -> int:
    name = name.strip()
    if not name:
        raise GasError("Le nom du grossiste est obligatoire.")
    with session_scope() as s:
        w = s.get(GasWholesaler, wholesaler_id) if wholesaler_id else None
        if w is None:
            if s.execute(select(GasWholesaler).where(func.lower(GasWholesaler.name) == name.lower())).first():
                raise GasError("Ce grossiste existe déjà.")
            w = GasWholesaler(name=name)
            s.add(w)
        w.name, w.phone, w.address, w.notes, w.active = name, phone.strip(), address.strip(), notes.strip(), active
        s.flush()
        return w.id


def list_wholesalers(active_only: bool = True) -> List[WholesalerRow]:
    with session_scope() as s:
        q = select(GasWholesaler).order_by(GasWholesaler.name)
        if active_only:
            q = q.where(GasWholesaler.active.is_(True))
        return [WholesalerRow(w.id, w.name, w.phone, w.address, w.notes, bool(w.active)) for w in s.execute(q).scalars()]


def deliver(wholesaler_id: int, items: Sequence[Tuple[int, int, Optional[float], Optional[int]]], when: Optional[datetime] = None,
            paid: float = 0, note: str = "", trip_id: Optional[int] = None) -> int:
    """Livraison à un grossiste. items = (line_id, pleines livrées, prix unitaire ou None = prix grossiste,
    vides reçues ou None = autant que de pleines). Retourne l'id de la livraison."""
    items = [i for i in items if i[1] and i[1] > 0]
    if not items:
        raise GasError("Aucune bouteille à livrer.")
    if paid < 0:
        raise GasError("Montant payé invalide.")
    when = when or datetime.now()
    with session_scope() as s:
        if s.get(GasWholesaler, wholesaler_id) is None:
            raise GasError("Grossiste introuvable.")
        _open_trip(s, trip_id)
        # stock cumulé par produit pour détecter les doublons de lignes
        need: Dict[int, int] = {}
        for line_id, qty, _p, _e in items:
            need[line_id] = need.get(line_id, 0) + int(qty)
        for line_id, qty in need.items():
            _need_stock(s, line_id, qty, trip_id)
        d = GasDelivery(wholesaler_id=wholesaler_id, delivered_at=when, note=note.strip())
        s.add(d)
        s.flush()
        for line_id, qty, price, back in items:
            ln = s.get(GasLine, line_id)
            unit = _f(ln.wholesale_price) if price is None else float(price)
            d.items.append(GasDeliveryItem(line_id=line_id, qty=int(qty), unit_price=unit,
                                           empties_back=int(qty if back is None else back)))
            _move(s, line_id, MOVE_DELIVERY, -int(qty), when, unit_price=unit, wholesaler_id=wholesaler_id, delivery_id=d.id, trip_id=trip_id)
        if paid:
            s.add(GasPayment(wholesaler_id=wholesaler_id, paid_at=when, amount=paid, note="Payé à la livraison"))
        return d.id


def pay(wholesaler_id: int, amount: float, when: Optional[datetime] = None, note: str = "") -> None:
    if amount <= 0:
        raise GasError("Montant invalide.")
    with session_scope() as s:
        if s.get(GasWholesaler, wholesaler_id) is None:
            raise GasError("Grossiste introuvable.")
        s.add(GasPayment(wholesaler_id=wholesaler_id, paid_at=when or datetime.now(), amount=amount, note=note.strip()))


def set_empties_back(delivery_id: int, line_id: int, empties: int) -> None:
    """Corrige le nombre de vides rendues pour une ligne de livraison (ex. le grossiste rend les manquantes plus tard)."""
    if empties < 0:
        raise GasError("Nombre invalide.")
    with session_scope() as s:
        for it in s.execute(select(GasDeliveryItem).where(GasDeliveryItem.delivery_id == delivery_id,
                                                          GasDeliveryItem.line_id == line_id)).scalars():
            it.empties_back = empties
            return
        raise GasError("Ligne de livraison introuvable.")


@dataclass
class Account:
    wholesaler_id: int
    name: str
    delivered: int
    empties_back: int
    amount_due: float          # total livré
    paid: float
    balance: float             # reste à payer
    bottles_owed: int          # vides à rendre (pleines livrées − vides rendues)

    @property
    def statement(self) -> str:
        return statement_sentence(self)


def statement_sentence(a: Account) -> str:
    if a.bottles_owed == 0 and abs(a.balance) < 0.5:
        return f"Compte juste : {a.empties_back} vides reçues, {a.delivered} pleines remises, {_money(a.paid)} payés"
    parts = []
    if a.bottles_owed > 0:
        parts.append(f"Il manque {a.bottles_owed} vide{'s' if a.bottles_owed > 1 else ''}")
    elif a.bottles_owed < 0:
        parts.append(f"{-a.bottles_owed} vide{'s' if a.bottles_owed < -1 else ''} en trop reçue{'s' if a.bottles_owed < -1 else ''}")
    if a.balance > 0.5:
        parts.append(f"il reste {_money(a.balance)} à payer")
    elif a.balance < -0.5:
        parts.append(f"{_money(-a.balance)} payés en avance")
    return (" et ".join(parts)).capitalize() if parts else ""


def _money(v: float) -> str:
    return f"{round(v):,}".replace(",", " ") + " F"


def wholesaler_account(wholesaler_id: int, until: Optional[datetime] = None) -> Account:
    with session_scope() as s:
        w = s.get(GasWholesaler, wholesaler_id)
        if w is None:
            raise GasError("Grossiste introuvable.")
        q = (select(func.coalesce(func.sum(GasDeliveryItem.qty), 0), func.coalesce(func.sum(GasDeliveryItem.empties_back), 0),
                    func.coalesce(func.sum(GasDeliveryItem.qty * GasDeliveryItem.unit_price), 0))
             .join(GasDelivery, GasDelivery.id == GasDeliveryItem.delivery_id).where(GasDelivery.wholesaler_id == wholesaler_id))
        pq = select(func.coalesce(func.sum(GasPayment.amount), 0)).where(GasPayment.wholesaler_id == wholesaler_id)
        if until is not None:
            q = q.where(GasDelivery.delivered_at < until)
            pq = pq.where(GasPayment.paid_at < until)
        qty, back, due = s.execute(q).one()
        paid = _f(s.execute(pq).scalar())
        return Account(w.id, w.name, int(qty), int(back), _f(due), paid, _f(due) - paid, int(qty) - int(back))


def deliveries_of_day(day: date, wholesaler_id: Optional[int] = None, trip_id: Optional[int] = None) -> List[dict]:
    """Feuille « Entrée » d'une journée : une ligne par grossiste (quantités par produit, total, payé)."""
    a, b = _day_bounds(day)
    with session_scope() as s:
        q = select(GasDelivery).where(GasDelivery.delivered_at >= a, GasDelivery.delivered_at < b).order_by(GasDelivery.delivered_at)
        if wholesaler_id:
            q = q.where(GasDelivery.wholesaler_id == wholesaler_id)
        if trip_id is not None:
            ids = select(GasMovement.delivery_id).where(GasMovement.trip_id == trip_id, GasMovement.delivery_id.is_not(None))
            q = q.where(GasDelivery.id.in_(ids))
        out = []
        for d in s.execute(q).scalars():
            w = s.get(GasWholesaler, d.wholesaler_id)
            lines = {}
            total = 0.0
            for it in d.items:
                lines[it.line_id] = lines.get(it.line_id, 0) + it.qty
                total += it.qty * _f(it.unit_price)
            out.append({"delivery_id": d.id, "wholesaler": w.name if w else "?", "lines": lines, "total": total,
                        "empties_back": sum(i.empties_back for i in d.items), "note": d.note})
        return out


# ---------------------------------------------------------------- cahier du jour
def day_sheet(day: date, trip_id: Optional[int] = None) -> List[dict]:
    """Une ligne par produit, comme le cahier : S.I (stock initial), Entrée, S.T, Vente, P.U moyen, Montant,
    Livré grossistes, Pertes, S.F (stock final). Les ventes et livraisons sont comptées séparément."""
    a, b = _day_bounds(day)
    with session_scope() as s:
        rows = []
        for ln in s.execute(select(GasLine).where(GasLine.active.is_(True)).order_by(GasLine.size_kg, GasLine.id)).scalars():
            si = stock_of(s, ln.id, before=a, trip_id=trip_id)
            sums: Dict[str, Tuple[int, float]] = {}
            for kind, qty, amount in s.execute(
                    select(GasMovement.kind, func.coalesce(func.sum(GasMovement.qty), 0),
                           func.coalesce(func.sum(func.abs(GasMovement.qty) * GasMovement.unit_price), 0))
                    .where(GasMovement.line_id == ln.id, GasMovement.moved_at >= a, GasMovement.moved_at < b,
                           GasMovement.trip_id.is_(None) if trip_id is None else GasMovement.trip_id == trip_id)
                    .group_by(GasMovement.kind)):
                sums[kind] = (int(qty), _f(amount))
            entry = sum(sums.get(k, (0, 0))[0] for k in (MOVE_ENTRY, MOVE_ADJUST, MOVE_TRANSFER))
            sold, amount = -sums.get(MOVE_SALE, (0, 0))[0], sums.get(MOVE_SALE, (0, 0))[1]
            delivered = -sums.get(MOVE_DELIVERY, (0, 0))[0]
            lost = -sums.get(MOVE_LOSS, (0, 0))[0]
            rows.append({"line_id": ln.id, "name": ln.name, "si": si, "entry": entry, "st": si + entry, "sold": sold,
                         "unit_price": (amount / sold) if sold else _f(ln.retail_price), "amount": amount,
                         "delivered": delivered, "lost": lost, "sf": si + entry - sold - delivered - lost})
        return rows


def day_total(day: date, trip_id: Optional[int] = None) -> float:
    return sum(r["amount"] for r in day_sheet(day, trip_id))


def losses(start: Optional[date] = None, end: Optional[date] = None) -> List[dict]:
    with session_scope() as s:
        q = select(GasMovement, GasLine.name).join(GasLine, GasLine.id == GasMovement.line_id).where(GasMovement.kind == MOVE_LOSS)
        if start:
            q = q.where(GasMovement.moved_at >= _day_bounds(start)[0])
        if end:
            q = q.where(GasMovement.moved_at < _day_bounds(end)[1])
        return [{"date": m.moved_at, "line": name, "qty": -m.qty, "reason": m.reason}
                for m, name in s.execute(q.order_by(GasMovement.moved_at)).all()]


# ---------------------------------------------------------------- chiffres (à part de la caisse)
def figures(start: date, end: date) -> dict:
    """Chiffre d'affaires gaz (ventes détaillants + livraisons grossistes), encaissé, dettes grossistes, bénéfice
    (seulement si tous les produits vendus ont un prix d'achat)."""
    a, b = _day_bounds(start)[0], _day_bounds(end)[1]
    with session_scope() as s:
        revenue, cost, missing = 0.0, 0.0, False
        for m, ln in s.execute(select(GasMovement, GasLine).join(GasLine, GasLine.id == GasMovement.line_id)
                               .where(GasMovement.kind.in_([MOVE_SALE, MOVE_DELIVERY]), GasMovement.moved_at >= a,
                                      GasMovement.moved_at < b)).all():
            qty = -m.qty
            revenue += qty * _f(m.unit_price)
            if ln.cost_price is None:
                missing = True
            else:
                cost += qty * _f(ln.cost_price)
        collected = _f(s.execute(select(func.coalesce(func.sum(GasPayment.amount), 0))
                                 .where(GasPayment.paid_at >= a, GasPayment.paid_at < b)).scalar())
        debts = sum(wholesaler_account(w.id).balance for w in list_wholesalers(active_only=False))
        return {"revenue": revenue, "payments": collected, "debts": debts,
                "profit": None if (missing and revenue) else revenue - cost}


# ---------------------------------------------------------------- camion : voyages
@dataclass
class TripRow:
    id: int
    number: str
    truck: str
    driver: str
    source: str
    started_at: datetime
    ended_at: Optional[datetime]
    status: str
    note: str
    loaded: int = 0
    remaining: int = 0

    @property
    def label(self) -> str:
        return f"{self.number} — {self.truck or 'camion'}" + (f" ({self.driver})" if self.driver else "")


def _next_trip_number(s) -> str:
    n = int(s.execute(select(func.count(GasTrip.id))).scalar() or 0) + 1
    while s.execute(select(GasTrip.id).where(GasTrip.number == f"V{n:03d}")).first():
        n += 1
    return f"V{n:03d}"


def start_trip(loads: Sequence[Tuple[int, int]], truck: str = "", driver: str = "", source: str = "SONABHY",
               when: Optional[datetime] = None, note: str = "") -> int:
    """Nouveau voyage : le chargement (pleines par produit) va dans le stock du camion, pas dans celui du dépôt."""
    loads = [(lid, int(q)) for lid, q in loads if q and q > 0]
    if not loads:
        raise GasError("Indiquez ce qui est chargé dans le camion.")
    when = when or datetime.now()
    with session_scope() as s:
        trip = GasTrip(number=_next_trip_number(s), truck=truck.strip(), driver=driver.strip(), source=source.strip() or "SONABHY",
                       started_at=when, note=note.strip())
        s.add(trip)
        s.flush()
        for lid, qty in loads:
            if s.get(GasLine, lid) is None:
                raise GasError("Produit gaz introuvable.")
            _move(s, lid, MOVE_ENTRY, qty, when, reason=f"Chargement {trip.source}", trip_id=trip.id)
        return trip.id


def _trip_row(s, t: GasTrip) -> TripRow:
    loaded = int(s.execute(select(func.coalesce(func.sum(GasMovement.qty), 0))
                           .where(GasMovement.trip_id == t.id, GasMovement.kind == MOVE_ENTRY, GasMovement.qty > 0)).scalar() or 0)
    remaining = int(s.execute(select(func.coalesce(func.sum(GasMovement.qty), 0)).where(GasMovement.trip_id == t.id)).scalar() or 0)
    return TripRow(t.id, t.number, t.truck, t.driver, t.source, t.started_at, t.ended_at, t.status, t.note, loaded, remaining)


def list_trips(open_only: bool = False) -> List[TripRow]:
    with session_scope() as s:
        q = select(GasTrip).order_by(GasTrip.started_at.desc(), GasTrip.id.desc())
        if open_only:
            q = q.where(GasTrip.status == TRIP_OPEN)
        return [_trip_row(s, t) for t in s.execute(q).scalars()]


def get_trip(trip_id: int) -> TripRow:
    with session_scope() as s:
        t = s.get(GasTrip, trip_id)
        if t is None:
            raise GasError("Voyage introuvable.")
        return _trip_row(s, t)


def trip_summary(trip_id: int) -> List[dict]:
    """Par produit : chargé, vendu aux détaillants, livré aux grossistes, pertes, restant dans le camion."""
    with session_scope() as s:
        out = []
        for ln in s.execute(select(GasLine).order_by(GasLine.size_kg, GasLine.id)).scalars():
            sums: Dict[str, int] = {}
            for kind, qty in s.execute(select(GasMovement.kind, func.coalesce(func.sum(GasMovement.qty), 0))
                                       .where(GasMovement.trip_id == trip_id, GasMovement.line_id == ln.id).group_by(GasMovement.kind)):
                sums[kind] = int(qty)
            if not sums:
                continue
            loaded = sums.get(MOVE_ENTRY, 0) + sums.get(MOVE_ADJUST, 0)
            out.append({"line_id": ln.id, "name": ln.name, "loaded": loaded, "sold": -sums.get(MOVE_SALE, 0),
                        "delivered": -sums.get(MOVE_DELIVERY, 0), "lost": -sums.get(MOVE_LOSS, 0),
                        "transferred": -sums.get(MOVE_TRANSFER, 0), "remaining": sum(sums.values())})
        return out


def empties_proposed(trip_id: int) -> Dict[float, int]:
    """Vides à remettre à la source, par taille : une vide pour chaque recharge vendue aux détaillants + les vides
    réellement reçues des grossistes. Les formules Consigné / Complet laissent la bouteille au client : aucune vide."""
    out: Dict[float, int] = {}
    with session_scope() as s:
        for ln, qty in s.execute(select(GasLine, func.coalesce(func.sum(-GasMovement.qty), 0))
                                 .join(GasMovement, GasMovement.line_id == GasLine.id)
                                 .where(GasMovement.trip_id == trip_id, GasMovement.kind == MOVE_SALE, GasLine.formula == FORMULA_RECHARGE)
                                 .group_by(GasLine.id)).all():
            out[_f(ln.size_kg)] = out.get(_f(ln.size_kg), 0) + int(qty)
        ids = select(GasMovement.delivery_id).where(GasMovement.trip_id == trip_id, GasMovement.kind == MOVE_DELIVERY,
                                                    GasMovement.delivery_id.is_not(None)).distinct()
        for ln, back in s.execute(select(GasLine, func.coalesce(func.sum(GasDeliveryItem.empties_back), 0))
                                  .join(GasDeliveryItem, GasDeliveryItem.line_id == GasLine.id)
                                  .where(GasDeliveryItem.delivery_id.in_(ids)).group_by(GasLine.id)).all():
            out[_f(ln.size_kg)] = out.get(_f(ln.size_kg), 0) + int(back)
    return {k: v for k, v in sorted(out.items()) if v}


def close_trip(trip_id: int, handed: Optional[Dict[float, int]] = None, when: Optional[datetime] = None, note: str = "") -> None:
    """Retour du camion à la source : remise des vides (proposées d'après les livraisons, modifiables) en échange, sans argent.
    Les pleines restantes retournent au stock du dépôt."""
    when = when or datetime.now()
    proposed = empties_proposed(trip_id)
    handed = dict(proposed) if handed is None else {float(k): int(v) for k, v in handed.items()}
    if any(v < 0 for v in handed.values()):
        raise GasError("Nombre de vides invalide.")
    with session_scope() as s:
        t = s.get(GasTrip, trip_id)
        if t is None:
            raise GasError("Voyage introuvable.")
        if t.status != TRIP_OPEN:
            raise GasError("Ce voyage est déjà terminé.")
        for size in sorted(set(proposed) | set(handed)):
            s.add(GasEmptiesReturn(trip_id=trip_id, size_kg=size, proposed=proposed.get(size, 0), handed=handed.get(size, 0)))
        for ln in s.execute(select(GasLine)).scalars():
            left = stock_of(s, ln.id, trip_id=trip_id)
            if left > 0:
                _move(s, ln.id, MOVE_TRANSFER, -left, when, reason=f"Reste du voyage {t.number}", trip_id=trip_id)
                _move(s, ln.id, MOVE_TRANSFER, left, when, reason=f"Reste du voyage {t.number}")
        t.status, t.ended_at = TRIP_CLOSED, when
        if note.strip():
            t.note = (t.note + "\n" + note.strip()).strip()


def empties_returned(trip_id: int) -> List[dict]:
    with session_scope() as s:
        return [{"size_kg": _f(r.size_kg), "proposed": r.proposed, "handed": r.handed}
                for r in s.execute(select(GasEmptiesReturn).where(GasEmptiesReturn.trip_id == trip_id).order_by(GasEmptiesReturn.size_kg)).scalars()]


def trip_days(trip_id: int) -> List[dict]:
    """Étapes jour par jour d'un voyage : qui a reçu quoi (détaillants ou grossiste), quantités par produit et montant."""
    with session_scope() as s:
        names = {ln.id: ln.name for ln in s.execute(select(GasLine)).scalars()}
        wh = {w.id: w.name for w in s.execute(select(GasWholesaler)).scalars()}
        days: Dict[date, dict] = {}
        for m in s.execute(select(GasMovement).where(GasMovement.trip_id == trip_id,
                                                      GasMovement.kind.in_([MOVE_SALE, MOVE_DELIVERY, MOVE_LOSS, MOVE_ENTRY]))
                           .order_by(GasMovement.moved_at, GasMovement.id)).scalars():
            d = m.moved_at.date()
            day = days.setdefault(d, {"date": d, "steps": {}, "total": 0.0})
            if m.kind == MOVE_ENTRY:
                who, kind = "Chargement", "chargement"
            elif m.kind == MOVE_SALE:
                who, kind = "Détaillants", "vente"
            elif m.kind == MOVE_LOSS:
                who, kind = "Pertes", "perte"
            else:
                who, kind = wh.get(m.wholesaler_id, "Grossiste"), "livraison"
            step = day["steps"].setdefault((kind, who), {"who": who, "kind": kind, "lines": {}, "amount": 0.0, "reasons": []})
            step["lines"][names.get(m.line_id, "?")] = step["lines"].get(names.get(m.line_id, "?"), 0) + abs(m.qty)
            if kind in ("vente", "livraison"):
                step["amount"] += abs(m.qty) * _f(m.unit_price)
                day["total"] += abs(m.qty) * _f(m.unit_price)
            if kind == "perte" and m.reason:
                step["reasons"].append(m.reason)
        return [{"date": d["date"], "steps": list(d["steps"].values()), "total": d["total"]} for _, d in sorted(days.items())]
