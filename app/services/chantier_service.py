"""Chantiers / marchés : devis → marché, dépenses, encaissements, avenants, avancement et résultat.

La question du directeur : « combien j'ai encaissé, combien j'ai dépensé, combien il me reste à recevoir,
et est-ce que je gagne de l'argent sur ce chantier ? ». Les charges générales (loyer, électricité…) restent
dans les Dépenses du commerce, séparées des chantiers.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app import config
from app.database.connection import session_scope
from app.models.chantier import (
    MARKET_STATUSES, STATUS_ACCEPTED, STATUS_DISPUTE, STATUS_DONE, STATUS_LABELS, STATUS_PAID, STATUS_QUOTE,
    STATUS_REFUSED, STATUS_RUNNING, Chantier, ChantierAddendum, ChantierExpense, ChantierLine, ChantierLot,
    ChantierMilestone, ChantierPayment, ChantierBudget,
)
from app.models.expense import Expense
from app.services import audit_service, settings_service
from app.utils.helpers import to_float

COUNTER_KEY = "chantier_counter"
RECEIPT_KEY = "chantier_receipt_counter"
DRIFT_ALERT_POINTS = 15.0     # dépenses consommées − avancement (en points) au-delà desquels on alerte
EPS = 0.0005
BUDGET_WARN_PCT = 90.0       # alerte quand un poste a consommé 90 % de son budget


def _f(value) -> float:
    return float(value or 0)


def _next(key: str, prefix: str, session, column) -> str:
    try:
        counter = int(settings_service.get_setting(key, "0") or 0)
    except ValueError:
        counter = 0
    numeric = []
    for number in session.scalars(select(column)):
        tail = str(number or "").rsplit("-", 1)[-1]
        if tail.isdigit():
            numeric.append(int(tail))
    counter = max([counter, *numeric]) + 1
    settings_service.set_setting(key, str(counter))
    return f"{prefix}-{counter:05d}"


# --- pièces jointes ------------------------------------------------------------
def attach_file(chantier_id: int, source: str | Path) -> str:
    """Copie un reçu / une facture / une photo dans le dossier du chantier ; retourne le chemin relatif stocké."""
    source = Path(source)
    if not source.is_file():
        raise ValueError("Fichier introuvable.")
    folder = config.DATA_DIR / "chantiers" / str(chantier_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = folder / f"{stamp}_{source.name}"
    shutil.copy2(source, target)
    return str(target.relative_to(config.DATA_DIR))


def attachment_path(relative: str) -> Optional[Path]:
    if not relative:
        return None
    path = config.DATA_DIR / relative
    return path if path.is_file() else None


# --- création / devis → marché -----------------------------------------------------
@dataclass
class LineInput:
    label: str
    quantity: float = 1.0
    unit: str = ""
    unit_price: float = 0.0
    category: str = "Matériel"


def create(name: str, *, client_id: Optional[int] = None, client_label: str = "", location: str = "",
           start_date: Optional[datetime] = None, end_planned: Optional[datetime] = None, amount: float = 0.0,
           status: str = STATUS_RUNNING, notes: str = "", lines: Optional[List[LineInput]] = None,
           retention_pct: float = 0.0, user_id: Optional[int] = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Donnez un nom au chantier.")
    if status not in STATUS_LABELS:
        raise ValueError("Statut inconnu.")
    with session_scope() as session:
        total_lines = sum(to_float(l.quantity) * to_float(l.unit_price) for l in (lines or []))
        chantier = Chantier(
            number=_next(COUNTER_KEY, "CH", session, Chantier.number), name=name, client_id=client_id,
            client_label=(client_label or "").strip(), location=(location or "").strip(), start_date=start_date,
            end_planned=end_planned, amount=to_float(amount) or round(total_lines, 3), status=status,
            notes=(notes or "").strip(), retention_pct=max(0.0, to_float(retention_pct)), user_id=user_id,
        )
        for line in lines or []:
            if (line.label or "").strip():
                chantier.lines.append(ChantierLine(label=line.label.strip(), quantity=to_float(line.quantity), unit=line.unit or "",
                                                   unit_price=to_float(line.unit_price), category=line.category or "Matériel"))
        session.add(chantier)
        session.flush()
        return chantier.id


def update(chantier_id: int, **fields) -> None:
    allowed = {"name", "client_id", "client_label", "location", "start_date", "end_planned", "amount", "notes",
               "retention_pct", "progress_mode"}
    with session_scope() as session:
        chantier = session.get(Chantier, chantier_id)
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in ("amount", "retention_pct"):
                value = max(0.0, to_float(value))
            if key == "name" and not str(value or "").strip():
                raise ValueError("Donnez un nom au chantier.")
            setattr(chantier, key, value)


def replace_lines(chantier_id: int, lines: List[LineInput]) -> None:
    with session_scope() as session:
        chantier = session.get(Chantier, chantier_id)
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        chantier.lines.clear()
        session.flush()
        for line in lines:
            if (line.label or "").strip():
                chantier.lines.append(ChantierLine(label=line.label.strip(), quantity=to_float(line.quantity), unit=line.unit or "",
                                                   unit_price=to_float(line.unit_price), category=line.category or "Matériel"))


_TRANSITIONS = {
    STATUS_QUOTE: {STATUS_ACCEPTED, STATUS_REFUSED, STATUS_RUNNING},
    STATUS_ACCEPTED: {STATUS_RUNNING, STATUS_REFUSED, STATUS_QUOTE},
    STATUS_REFUSED: {STATUS_QUOTE},
    STATUS_RUNNING: {STATUS_DONE, STATUS_PAID, STATUS_DISPUTE},
    STATUS_DONE: {STATUS_RUNNING, STATUS_PAID, STATUS_DISPUTE},
    STATUS_PAID: {STATUS_DONE},
    STATUS_DISPUTE: {STATUS_RUNNING, STATUS_DONE, STATUS_PAID},
}


def set_status(chantier_id: int, status: str) -> None:
    if status not in STATUS_LABELS:
        raise ValueError("Statut inconnu.")
    with session_scope() as session:
        chantier = session.get(Chantier, chantier_id)
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        if status != chantier.status and status not in _TRANSITIONS.get(chantier.status, set()):
            raise ValueError(f"Passage impossible : « {STATUS_LABELS[chantier.status]} » → « {STATUS_LABELS[status]} ».")
        chantier.status = status


def convert_to_market(chantier_id: int) -> None:
    """Devis accepté → marché en cours : le montant du devis devient le prix du marché, les lignes le budget."""
    with session_scope() as session:
        chantier = session.execute(select(Chantier).options(joinedload(Chantier.lines)).where(Chantier.id == chantier_id)).unique().scalar_one_or_none()
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        if chantier.status not in (STATUS_QUOTE, STATUS_ACCEPTED):
            raise ValueError("Seul un devis peut être converti en marché.")
        if not _f(chantier.amount):
            chantier.amount = round(sum(l.total for l in chantier.lines), 3)
        if not _f(chantier.amount):
            raise ValueError("Le devis n'a pas de montant : ajoutez des lignes ou un montant.")
        chantier.status = STATUS_RUNNING
        chantier.converted_at = datetime.now()
        if chantier.start_date is None:
            chantier.start_date = datetime.now()


def delete(chantier_id: int) -> None:
    """Suppression refusée dès qu'il y a de l'argent engagé (dépenses ou encaissements) : on archive plutôt."""
    with session_scope() as session:
        chantier = session.get(Chantier, chantier_id)
        if chantier is None:
            return
        if chantier.expenses or chantier.payments:
            raise ValueError("Ce chantier a des dépenses ou des encaissements : il ne peut pas être supprimé.")
        session.delete(chantier)


# --- dépenses ------------------------------------------------------------------------
def add_expense(chantier_id: int, *, category: str, label: str = "", amount: float = 0.0, amount_paid: Optional[float] = None,
                supplier: str = "", date: Optional[datetime] = None, worker: str = "", days: float = 0.0,
                daily_rate: float = 0.0, attachment_source: str | Path | None = None, notes: str = "",
                user_id: Optional[int] = None) -> int:
    days, daily_rate = max(0.0, to_float(days)), max(0.0, to_float(daily_rate))
    amount = to_float(amount) or round(days * daily_rate, 3)       # main-d'œuvre : jours × tarif
    if amount <= 0:
        raise ValueError("Le montant de la dépense doit être supérieur à zéro.")
    paid = amount if amount_paid is None else max(0.0, min(to_float(amount_paid), amount))
    with session_scope() as session:
        chantier = session.get(Chantier, chantier_id)
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        if chantier.status in (STATUS_QUOTE, STATUS_ACCEPTED, STATUS_REFUSED):
            raise ValueError("Convertissez d'abord le devis en marché avant de saisir des dépenses.")
        expense = ChantierExpense(
            chantier_id=chantier_id, category=category or "Divers", label=(label or worker or "").strip(), supplier=(supplier or "").strip(),
            date=date or datetime.now(), amount=amount, amount_paid=paid, worker=(worker or "").strip(), days=days, daily_rate=daily_rate,
            notes=(notes or "").strip(), user_id=user_id,
        )
        if attachment_source:
            expense.attachment = attach_file(chantier_id, attachment_source)
        session.add(expense)
        session.flush()
        return expense.id


def pay_expense(expense_id: int, amount: float) -> None:
    """Règle une dette fournisseur (paiement du reste à payer d'une dépense à crédit)."""
    with session_scope() as session:
        expense = session.get(ChantierExpense, expense_id)
        if expense is None:
            raise ValueError("Dépense introuvable.")
        due = _f(expense.amount) - _f(expense.amount_paid)
        value = to_float(amount)
        if value <= 0 or value > due + EPS:
            raise ValueError(f"Le paiement doit être compris entre 0 et {due:g}.")
        expense.amount_paid = _f(expense.amount_paid) + value


def delete_expense(expense_id: int) -> None:
    with session_scope() as session:
        expense = session.get(ChantierExpense, expense_id)
        if expense is not None:
            session.delete(expense)


# --- encaissements -----------------------------------------------------------------------
def add_payment(chantier_id: int, *, amount: float, kind: str = "Tranche", method: str = "Espèces", reference: str = "",
                date: Optional[datetime] = None, attachment_source: str | Path | None = None, notes: str = "",
                user_id: Optional[int] = None) -> int:
    value = to_float(amount)
    if value <= 0:
        raise ValueError("Le montant encaissé doit être supérieur à zéro.")
    with session_scope() as session:
        chantier = session.execute(select(Chantier).options(joinedload(Chantier.addenda), joinedload(Chantier.payments)).where(Chantier.id == chantier_id)).unique().scalar_one_or_none()
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        if chantier.status in (STATUS_QUOTE, STATUS_ACCEPTED, STATUS_REFUSED):
            raise ValueError("Convertissez d'abord le devis en marché avant d'encaisser.")
        contract = _f(chantier.amount) + sum(_f(a.amount) for a in chantier.addenda)
        received = sum(_f(p.amount) for p in chantier.payments)
        if received + value > contract + EPS:
            raise ValueError(f"Ce paiement dépasse le montant du marché (reste à encaisser : {max(0.0, contract - received):g}).")
        payment = ChantierPayment(chantier_id=chantier_id, number=_next(RECEIPT_KEY, "RC", session, ChantierPayment.number), date=date or datetime.now(),
                                  kind=kind or "Tranche", amount=value, method=method or "Espèces", reference=(reference or "").strip(),
                                  notes=(notes or "").strip(), user_id=user_id)
        if attachment_source:
            payment.attachment = attach_file(chantier_id, attachment_source)
        session.add(payment)
        session.flush()
        return payment.id


def delete_payment(payment_id: int) -> None:
    with session_scope() as session:
        payment = session.get(ChantierPayment, payment_id)
        if payment is not None:
            session.delete(payment)


# --- avenants, lots, échéancier -----------------------------------------------------------
def add_addendum(chantier_id: int, *, label: str, amount: float, date: Optional[datetime] = None, notes: str = "",
                 attachment_source: str | Path | None = None, user_id: Optional[int] = None) -> int:
    value = to_float(amount)
    if not (label or "").strip():
        raise ValueError("Décrivez l'avenant (travaux supplémentaires).")
    if abs(value) < EPS:
        raise ValueError("Le montant de l'avenant ne peut pas être nul.")
    with session_scope() as session:
        chantier = session.get(Chantier, chantier_id)
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        number = (session.scalar(select(func.max(ChantierAddendum.number)).where(ChantierAddendum.chantier_id == chantier_id)) or 0) + 1
        addendum = ChantierAddendum(chantier_id=chantier_id, number=number, date=date or datetime.now(), label=label.strip(), amount=value,
                                    notes=(notes or "").strip(), user_id=user_id)
        if attachment_source:
            addendum.attachment = attach_file(chantier_id, attachment_source)
        session.add(addendum)
        session.flush()
        return addendum.id


def add_lot(chantier_id: int, label: str, weight: float) -> int:
    if not (label or "").strip():
        raise ValueError("Nommez le lot.")
    weight = to_float(weight)
    if not 0 < weight <= 100:
        raise ValueError("Le poids d'un lot doit être compris entre 0 et 100 %.")
    with session_scope() as session:
        total = sum(_f(w) for w in session.scalars(select(ChantierLot.weight).where(ChantierLot.chantier_id == chantier_id)))
        if total + weight > 100 + EPS:
            raise ValueError(f"Le total des poids dépasserait 100 % (déjà {total:g} %).")
        lot = ChantierLot(chantier_id=chantier_id, label=label.strip(), weight=weight)
        session.add(lot)
        session.flush()
        return lot.id


def set_lot_done(lot_id: int, done: bool) -> None:
    with session_scope() as session:
        lot = session.get(ChantierLot, lot_id)
        if lot is not None:
            lot.done = bool(done)


def delete_lot(lot_id: int) -> None:
    with session_scope() as session:
        lot = session.get(ChantierLot, lot_id)
        if lot is not None:
            session.delete(lot)


def set_progress(chantier_id: int, pct: float) -> None:
    """Avancement saisi à la main par le chef de chantier (mode manuel)."""
    with session_scope() as session:
        chantier = session.get(Chantier, chantier_id)
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        chantier.progress_pct = max(0.0, min(100.0, to_float(pct)))
        chantier.progress_mode = "manuel"


def add_milestone(chantier_id: int, label: str, pct: float, due_date: Optional[datetime] = None) -> int:
    if not (label or "").strip():
        raise ValueError("Nommez l'échéance (ex. « À la signature »).")
    pct = to_float(pct)
    if not 0 < pct <= 100:
        raise ValueError("Le pourcentage doit être compris entre 0 et 100.")
    with session_scope() as session:
        total = sum(_f(w) for w in session.scalars(select(ChantierMilestone.pct).where(ChantierMilestone.chantier_id == chantier_id)))
        if total + pct > 100 + EPS:
            raise ValueError(f"L'échéancier dépasserait 100 % (déjà {total:g} %).")
        milestone = ChantierMilestone(chantier_id=chantier_id, label=label.strip(), pct=pct, due_date=due_date)
        session.add(milestone)
        session.flush()
        return milestone.id


def delete_milestone(milestone_id: int) -> None:
    with session_scope() as session:
        milestone = session.get(ChantierMilestone, milestone_id)
        if milestone is not None:
            session.delete(milestone)


# --- budget par poste --------------------------------------------------------------------
def set_budget(chantier_id: int, amounts: dict) -> None:
    """Remplace le budget de dépenses prévu : {poste: montant}. Un montant à 0 retire le poste."""
    with session_scope() as session:
        chantier = session.get(Chantier, chantier_id)
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        existing = {b.category: b for b in chantier.budgets}
        for cat, raw in amounts.items():
            value = to_float(raw)
            if value < 0:
                raise ValueError("Un budget ne peut pas être négatif.")
            row = existing.get(cat)
            if value == 0:
                if row is not None:
                    session.delete(row)
            elif row is not None:
                row.amount = value
            else:
                chantier.budgets.append(ChantierBudget(category=cat, amount=value))


def budget_from_quote(chantier_id: int) -> None:
    """Pré-remplit le budget avec les lignes du devis regroupées par poste (à ajuster ensuite)."""
    with session_scope() as session:
        chantier = session.execute(select(Chantier).options(joinedload(Chantier.lines)).where(Chantier.id == chantier_id)).unique().scalar_one_or_none()
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        totals: dict = {}
        for l in chantier.lines:
            totals[l.category] = totals.get(l.category, 0.0) + l.total
    set_budget(chantier_id, totals)


# --- résultat -------------------------------------------------------------------------------
@dataclass
class Summary:
    chantier_id: int
    number: str
    name: str
    status: str
    contract: float = 0.0            # marché + avenants
    base_amount: float = 0.0
    addenda_total: float = 0.0
    received: float = 0.0            # encaissé
    remaining_to_receive: float = 0.0
    spent: float = 0.0               # dépenses engagées
    paid_out: float = 0.0            # dépenses réellement payées
    supplier_debt: float = 0.0       # dépenses à crédit non réglées
    margin: float = 0.0              # marché − dépenses
    margin_pct: float = 0.0
    cash: float = 0.0                # trésorerie = encaissé − payé
    progress_pct: float = 0.0
    spent_pct: float = 0.0           # dépenses / marché
    budget: float = 0.0              # budget prévisionnel (lignes du devis)
    by_category: dict = field(default_factory=dict)
    cost_budget: dict = field(default_factory=dict)      # budget de dépenses prévu par poste
    cost_budget_total: float = 0.0
    retention_pct: float = 0.0       # retenue de garantie retenue par le client
    retention_amount: float = 0.0    # = marché × pourcentage
    retention_released: float = 0.0  # déjà reversée par le client (encaissements « Retenue de garantie »)
    retention_held: float = 0.0      # encore détenue par le client
    collectable_now: float = 0.0     # facturable avant réception (marché − retenue − déjà encaissé hors retenue)
    planned_vs_received: List[tuple] = field(default_factory=list)   # (libellé, prévu, cumul prévu, échéance)
    alerts: List[str] = field(default_factory=list)


def progress_of(chantier: Chantier) -> float:
    if chantier.progress_mode == "lots" and chantier.lots:
        total = sum(_f(l.weight) for l in chantier.lots)
        done = sum(_f(l.weight) for l in chantier.lots if l.done)
        return round(done * 100 / total, 2) if total else 0.0
    return round(_f(chantier.progress_pct), 2)


def _summarize(chantier: Chantier) -> Summary:
    base = _f(chantier.amount)
    addenda = sum(_f(a.amount) for a in chantier.addenda)
    contract = base + addenda
    received = sum(_f(p.amount) for p in chantier.payments)
    spent = sum(_f(e.amount) for e in chantier.expenses)
    paid_out = sum(_f(e.amount_paid) for e in chantier.expenses)
    by_category: dict = {}
    for e in chantier.expenses:
        by_category[e.category] = by_category.get(e.category, 0.0) + _f(e.amount)
    progress = progress_of(chantier)
    cost_budget = {b.category: _f(b.amount) for b in chantier.budgets if _f(b.amount) > 0}
    s = Summary(
        chantier_id=chantier.id, number=chantier.number, name=chantier.name, status=chantier.status, contract=contract,
        base_amount=base, addenda_total=addenda, received=received, remaining_to_receive=max(0.0, contract - received),
        spent=spent, paid_out=paid_out, supplier_debt=spent - paid_out, margin=contract - spent,
        margin_pct=round((contract - spent) * 100 / contract, 2) if contract else 0.0, cash=received - paid_out,
        progress_pct=progress, spent_pct=round(spent * 100 / contract, 2) if contract else 0.0,
        budget=sum(l.total for l in chantier.lines), by_category=by_category,
        cost_budget=cost_budget, cost_budget_total=sum(cost_budget.values()),
    )
    s.retention_pct = _f(chantier.retention_pct)
    s.retention_amount = round(contract * s.retention_pct / 100, 3)
    s.retention_released = sum(_f(p.amount) for p in chantier.payments if p.kind == "Retenue de garantie")
    s.retention_held = max(0.0, s.retention_amount - s.retention_released)
    s.collectable_now = max(0.0, contract - s.retention_amount - (received - s.retention_released))
    cumulative = 0.0
    for m in sorted(chantier.milestones, key=lambda m: (m.due_date or datetime.max, m.id)):
        planned = round(contract * _f(m.pct) / 100, 3)
        cumulative += planned
        s.planned_vs_received.append((m.label, planned, cumulative, m.due_date))
    if chantier.status in MARKET_STATUSES:
        if contract and spent > contract + EPS:
            s.alerts.append("Chantier en perte : les dépenses dépassent le montant du marché.")
        elif contract and s.spent_pct - progress >= DRIFT_ALERT_POINTS and spent > 0:
            s.alerts.append(f"Dérapage : {s.spent_pct:g} % du marché dépensé pour {progress:g} % d'avancement.")
        for cat, planned in cost_budget.items():
            used = by_category.get(cat, 0.0)
            if used > planned + EPS:
                s.alerts.append(f"Budget dépassé « {cat} » : {used:g} dépensé pour {planned:g} prévu.")
            elif planned and used >= planned * BUDGET_WARN_PCT / 100:
                s.alerts.append(f"Budget « {cat} » presque épuisé : {used * 100 / planned:.0f} % consommé.")
        if chantier.status in (STATUS_DONE, STATUS_PAID) and s.retention_held > EPS:
            s.alerts.append(f"Retenue de garantie à réclamer au client : {s.retention_held:g} ({s.retention_pct:g} % du marché).")
        late = [label for label, _p, cum, due in s.planned_vs_received if due and due < datetime.now() and received + EPS < cum]
        if late:
            s.alerts.append("Encaissement en retard : " + ", ".join(late) + ".")
    return s


def summary(chantier_id: int) -> Summary:
    with session_scope() as session:
        chantier = session.execute(
            select(Chantier).options(joinedload(Chantier.lines), joinedload(Chantier.expenses), joinedload(Chantier.payments),
                                     joinedload(Chantier.addenda), joinedload(Chantier.lots), joinedload(Chantier.milestones), joinedload(Chantier.budgets))
            .where(Chantier.id == chantier_id)).unique().scalar_one_or_none()
        if chantier is None:
            raise ValueError("Chantier introuvable.")
        return _summarize(chantier)


def list_summaries(status: str | None = None, search: str = "") -> List[Summary]:
    with session_scope() as session:
        query = select(Chantier).options(joinedload(Chantier.lines), joinedload(Chantier.expenses), joinedload(Chantier.payments),
                                         joinedload(Chantier.addenda), joinedload(Chantier.lots), joinedload(Chantier.milestones), joinedload(Chantier.budgets)).order_by(Chantier.id.desc())
        if status:
            query = query.where(Chantier.status == status)
        rows = session.execute(query).unique().scalars().all()
        needle = (search or "").strip().casefold()
        if needle:
            rows = [c for c in rows if needle in f"{c.number} {c.name} {c.client_label} {c.location}".casefold()]
        return [_summarize(c) for c in rows]


@dataclass
class GlobalResult:
    received: float = 0.0
    spent_paid: float = 0.0
    margins: float = 0.0
    overheads: float = 0.0           # charges générales (Dépenses du commerce)
    net_cash: float = 0.0            # encaissé − payé chantiers − charges générales
    net_profit: float = 0.0          # marges des marchés − charges générales
    receivable: float = 0.0          # reste à encaisser sur tous les marchés
    supplier_debt: float = 0.0
    running: int = 0
    losing: int = 0


def global_result(start: datetime | None = None, end: datetime | None = None) -> GlobalResult:
    """Résultat de l'entreprise sur une période : mouvements datés (encaissé, payé, charges) + situation des marchés."""
    with session_scope() as session:
        pay_q, exp_q, over_q = select(func.coalesce(func.sum(ChantierPayment.amount), 0)), select(func.coalesce(func.sum(ChantierExpense.amount_paid), 0)), select(func.coalesce(func.sum(Expense.amount), 0))
        if start:
            pay_q, exp_q, over_q = pay_q.where(ChantierPayment.date >= start), exp_q.where(ChantierExpense.date >= start), over_q.where(Expense.date >= start)
        if end:
            pay_q, exp_q, over_q = pay_q.where(ChantierPayment.date < end), exp_q.where(ChantierExpense.date < end), over_q.where(Expense.date < end)
        result = GlobalResult(received=_f(session.scalar(pay_q)), spent_paid=_f(session.scalar(exp_q)), overheads=_f(session.scalar(over_q)))
    markets = [s for s in list_summaries() if s.status in MARKET_STATUSES]
    result.margins = sum(s.margin for s in markets)
    result.receivable = sum(s.remaining_to_receive for s in markets)
    result.supplier_debt = sum(s.supplier_debt for s in markets)
    result.running = sum(1 for s in markets if s.status == STATUS_RUNNING)
    result.losing = sum(1 for s in markets if s.margin < -EPS)
    result.net_cash = result.received - result.spent_paid - result.overheads
    result.net_profit = result.margins - result.overheads
    return result
