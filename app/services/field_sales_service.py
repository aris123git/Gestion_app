"""Ventes en tournée : sortie de marchandise, retour du soir, écarts, commissions cumulées, boutiques visitées.

Principe : la marchandise sortie n'est pas retirée du stock tout de suite, elle est seulement « réservée » (pour ne pas
la vendre deux fois au dépôt). À la clôture, ce qui n'est pas revenu est vendu dans la caisse (ticket, marge, rapports).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.database.connection import session_scope
from app.models.client import Client
from app.models.field_sales import (
    RULE_FIXED, RULE_PERCENT, RUN_CLOSED, RUN_OPEN, SCOPE_CATEGORY, SCOPE_DEFAULT, SCOPE_PRODUCT, FieldCommissionPayment,
    FieldCommissionRule, FieldRun, FieldRunLine, FieldSeller, FieldVisit,
)
from app.models.product import Product
from app.services import settings_service
from app.services.chantier_service import _next
from app.utils.helpers import to_float

SETTING_ENABLED = "field_sales_enabled"
SETTING_ON_CASH = "field_commission_on_cash"      # 1 : commission réduite en proportion de l'argent réellement rapporté
COUNTER_KEY = "field_run_counter"
EPS = 0.0005


def _f(v) -> float:
    return float(v or 0)


def enabled() -> bool:
    return settings_service.get_setting(SETTING_ENABLED, "0") == "1"


def set_enabled(value: bool) -> None:
    settings_service.set_setting(SETTING_ENABLED, "1" if value else "0")


def commission_on_cash() -> bool:
    return settings_service.get_setting(SETTING_ON_CASH, "0") == "1"


def set_commission_on_cash(value: bool) -> None:
    settings_service.set_setting(SETTING_ON_CASH, "1" if value else "0")


# --- vendeurs ---------------------------------------------------------------------------------
def save_seller(*, seller_id: Optional[int] = None, name: str, phone: str = "", active: bool = True) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Donnez le nom du vendeur.")
    with session_scope() as session:
        dup = session.scalar(select(FieldSeller).where(func.lower(FieldSeller.name) == name.lower()))
        if dup is not None and dup.id != seller_id:
            raise ValueError("Ce vendeur existe déjà.")
        row = session.get(FieldSeller, seller_id) if seller_id else FieldSeller()
        if row is None:
            raise ValueError("Vendeur introuvable.")
        row.name, row.phone, row.active = name, (phone or "").strip(), bool(active)
        session.add(row)
        session.flush()
        return row.id


def list_sellers(include_inactive: bool = False) -> List[FieldSeller]:
    with session_scope() as session:
        q = select(FieldSeller).order_by(FieldSeller.name)
        if not include_inactive:
            q = q.where(FieldSeller.active.is_(True))
        rows = list(session.scalars(q))
        session.expunge_all()
        return rows


def delete_seller(seller_id: int) -> None:
    with session_scope() as session:
        if session.scalar(select(func.count()).select_from(FieldRun).where(FieldRun.seller_id == seller_id)):
            raise ValueError("Ce vendeur a des tournées : désactivez-le plutôt que de le supprimer.")
        row = session.get(FieldSeller, seller_id)
        if row is not None:
            session.delete(row)


def seller_debt(seller_id: int) -> float:
    with session_scope() as session:
        seller = session.get(FieldSeller, seller_id)
        if seller is None or not seller.debt_client_id:
            return 0.0
        client = session.get(Client, seller.debt_client_id)
        return max(0.0, _f(client.debt)) if client else 0.0


def _debt_client(session, seller: FieldSeller) -> int:
    """Compte client qui porte la dette du vendeur (créé à la première fois)."""
    if seller.debt_client_id and session.get(Client, seller.debt_client_id) is not None:
        return seller.debt_client_id
    client = Client(name=f"Vendeur — {seller.name}", phone=seller.phone or "", no_marketing=True,
                    notes="Compte technique : dette d'un vendeur en tournée.")
    session.add(client)
    session.flush()
    seller.debt_client_id = client.id
    return client.id


# --- règles de commission ----------------------------------------------------------------------------
def set_rule(scope: str, ref_id: Optional[int], kind: str, value: float) -> None:
    """Définit (ou retire si la valeur est 0) la règle d'un produit, d'une catégorie, ou la règle par défaut."""
    if scope not in (SCOPE_PRODUCT, SCOPE_CATEGORY, SCOPE_DEFAULT):
        raise ValueError("Portée inconnue.")
    if kind not in (RULE_PERCENT, RULE_FIXED):
        raise ValueError("Type de commission inconnu.")
    amount = to_float(value)
    if amount < 0 or (kind == RULE_PERCENT and amount > 100):
        raise ValueError("Valeur de commission invalide.")
    if scope != SCOPE_DEFAULT and not ref_id:
        raise ValueError("Choisissez le produit ou la catégorie.")
    with session_scope() as session:
        q = select(FieldCommissionRule).where(FieldCommissionRule.scope == scope)
        q = q.where(FieldCommissionRule.ref_id == (None if scope == SCOPE_DEFAULT else ref_id))
        row = session.scalar(q)
        if amount == 0:
            if row is not None:
                session.delete(row)
            return
        if row is None:
            row = FieldCommissionRule(scope=scope, ref_id=None if scope == SCOPE_DEFAULT else ref_id)
            session.add(row)
        row.kind, row.value = kind, amount


def list_rules() -> List[dict]:
    from app.models.category import Category

    with session_scope() as session:
        out = []
        for r in session.scalars(select(FieldCommissionRule).order_by(FieldCommissionRule.scope, FieldCommissionRule.id)):
            if r.scope == SCOPE_PRODUCT:
                p = session.get(Product, r.ref_id)
                target = p.name if p else f"#{r.ref_id}"
            elif r.scope == SCOPE_CATEGORY:
                c = session.get(Category, r.ref_id)
                target = c.name if c else f"#{r.ref_id}"
            else:
                target = "Tous les autres produits"
            out.append({"id": r.id, "scope": r.scope, "ref_id": r.ref_id, "target": target, "kind": r.kind, "value": _f(r.value)})
        return out


def delete_rule(rule_id: int) -> None:
    with session_scope() as session:
        row = session.get(FieldCommissionRule, rule_id)
        if row is not None:
            session.delete(row)


def _rule_for(session, product: Optional[Product]) -> Optional[tuple]:
    """Produit d'abord, puis sa catégorie, puis la règle par défaut."""
    if product is not None:
        for scope, ref in ((SCOPE_PRODUCT, product.id), (SCOPE_CATEGORY, product.category_id)):
            if ref:
                row = session.scalar(select(FieldCommissionRule).where(FieldCommissionRule.scope == scope, FieldCommissionRule.ref_id == ref))
                if row is not None:
                    return row.kind, _f(row.value)
    row = session.scalar(select(FieldCommissionRule).where(FieldCommissionRule.scope == SCOPE_DEFAULT))
    return (row.kind, _f(row.value)) if row is not None else None


def line_commission(rule: Optional[tuple], sold: float, unit_price: float) -> float:
    if rule is None or sold <= 0:
        return 0.0
    kind, value = rule
    return round(sold * unit_price * value / 100, 3) if kind == RULE_PERCENT else round(sold * value, 3)


# --- sorties ----------------------------------------------------------------------------------------------
def reserved_quantities(session=None) -> Dict[int, float]:
    """Quantités actuellement dehors (sorties non clôturées), par produit."""
    def run(s):
        q = (select(FieldRunLine.product_id, func.coalesce(func.sum(FieldRunLine.qty_out), 0)).join(FieldRun, FieldRun.id == FieldRunLine.run_id)
             .where(FieldRun.status == RUN_OPEN).group_by(FieldRunLine.product_id))
        return {pid: _f(q_) for pid, q_ in s.execute(q)}

    if session is not None:
        return run(session)
    with session_scope() as s:
        return run(s)


@dataclass
class ProductChoice:
    id: int
    name: str
    price: float
    stock: float
    reserved: float

    @property
    def available(self) -> float:
        return max(0.0, self.stock - self.reserved)


def product_choices() -> List[ProductChoice]:
    with session_scope() as session:
        reserved = reserved_quantities(session)
        return [ProductChoice(p.id, p.name, _f(p.sale_price), _f(p.quantity), reserved.get(p.id, 0.0))
                for p in session.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.name))]


@dataclass
class LineInput:
    product_id: int
    quantity: float
    unit_price: Optional[float] = None


def _check_available(session, product: Product, wanted: float, reserved: Dict[int, float]) -> None:
    if getattr(product, "sell_without_stock", False):
        return
    free = _f(product.quantity) - reserved.get(product.id, 0.0)
    if wanted > free + EPS:
        raise ValueError(f"« {product.name} » : seulement {max(0.0, free):g} disponible(s) (le reste est déjà dehors ou en rupture).")


def open_run(seller_id: int, lines: List[LineInput], *, notes: str = "", user_id: Optional[int] = None) -> int:
    if not lines:
        raise ValueError("Ajoutez au moins un produit.")
    with session_scope() as session:
        seller = session.get(FieldSeller, seller_id)
        if seller is None or not seller.active:
            raise ValueError("Vendeur introuvable ou inactif.")
        if session.scalar(select(func.count()).select_from(FieldRun).where(FieldRun.seller_id == seller_id, FieldRun.status == RUN_OPEN)):
            raise ValueError(f"{seller.name} a déjà une sortie en cours : clôturez-la d'abord (ou ajoutez des produits à cette sortie).")
        reserved = reserved_quantities(session)
        run = FieldRun(number=_next(COUNTER_KEY, "TOU", session, FieldRun.number), seller_id=seller_id, notes=(notes or "").strip(), user_id=user_id)
        merged: Dict[int, LineInput] = {}
        for li in lines:
            qty = to_float(li.quantity)
            if qty <= 0:
                raise ValueError("Une quantité doit être supérieure à zéro.")
            cur = merged.get(li.product_id)
            merged[li.product_id] = LineInput(li.product_id, (cur.quantity if cur else 0) + qty, li.unit_price if li.unit_price is not None else (cur.unit_price if cur else None))
        for pid, li in merged.items():
            product = session.get(Product, pid)
            if product is None:
                raise ValueError("Produit introuvable.")
            _check_available(session, product, li.quantity, reserved)
            price = _f(product.sale_price) if li.unit_price is None else max(0.0, to_float(li.unit_price))
            run.lines.append(FieldRunLine(product_id=pid, product_name=product.name, qty_out=li.quantity, unit_price=price))
        session.add(run)
        session.flush()
        return run.id


def add_to_run(run_id: int, product_id: int, quantity: float, unit_price: Optional[float] = None) -> None:
    """Le vendeur repasse au dépôt : on ajoute des produits à sa sortie en cours."""
    qty = to_float(quantity)
    if qty <= 0:
        raise ValueError("La quantité doit être supérieure à zéro.")
    with session_scope() as session:
        run = session.execute(select(FieldRun).options(joinedload(FieldRun.lines)).where(FieldRun.id == run_id)).unique().scalar_one_or_none()
        if run is None or run.status != RUN_OPEN:
            raise ValueError("Sortie introuvable ou déjà clôturée.")
        product = session.get(Product, product_id)
        if product is None:
            raise ValueError("Produit introuvable.")
        _check_available(session, product, qty, reserved_quantities(session))
        line = next((l for l in run.lines if l.product_id == product_id), None)
        if line is None:
            price = _f(product.sale_price) if unit_price is None else max(0.0, to_float(unit_price))
            run.lines.append(FieldRunLine(product_id=product_id, product_name=product.name, qty_out=qty, unit_price=price))
        else:
            line.qty_out = _f(line.qty_out) + qty


# --- retour du soir ------------------------------------------------------------------------------------------
@dataclass
class CloseLine:
    line_id: int
    product_id: int
    name: str
    qty_out: float
    qty_back: float
    sold: float
    unit_price: float
    value: float
    commission: float


@dataclass
class ClosePreview:
    lines: List[CloseLine] = field(default_factory=list)
    expected: float = 0.0
    cash: float = 0.0
    shortage: float = 0.0          # > 0 : manque ; < 0 : surplus
    commission: float = 0.0
    factor: float = 1.0


def preview_close(run_id: int, backs: Dict[int, float], prices: Optional[Dict[int, float]] = None, cash: float = 0.0) -> ClosePreview:
    prices = prices or {}
    with session_scope() as session:
        run = session.execute(select(FieldRun).options(joinedload(FieldRun.lines)).where(FieldRun.id == run_id)).unique().scalar_one_or_none()
        if run is None:
            raise ValueError("Sortie introuvable.")
        out = ClosePreview(cash=max(0.0, to_float(cash)))
        for l in run.lines:
            back = to_float(backs.get(l.id, 0))
            if back < 0 or back > _f(l.qty_out) + EPS:
                raise ValueError(f"« {l.product_name} » : le retour ({back:g}) dépasse ce qui est sorti ({_f(l.qty_out):g}).")
            price = max(0.0, to_float(prices.get(l.id, l.unit_price)))
            sold = round(_f(l.qty_out) - back, 3)
            product = session.get(Product, l.product_id)
            comm = line_commission(_rule_for(session, product), sold, price)
            out.lines.append(CloseLine(l.id, l.product_id, l.product_name, _f(l.qty_out), back, sold, price, round(sold * price, 3), comm))
        out.expected = round(sum(x.value for x in out.lines), 3)
        out.shortage = round(out.expected - out.cash, 3)
        gross = round(sum(x.commission for x in out.lines), 3)
        if commission_on_cash() and out.shortage > EPS and out.expected > 0:
            out.factor = max(0.0, out.cash / out.expected)
        out.commission = round(gross * out.factor, 3)
        return out


def close_run(run_id: int, backs: Dict[int, float], prices: Optional[Dict[int, float]] = None, *, cash_received: float = 0.0,
              charge_shortage: bool = False, user_id: Optional[int] = None) -> ClosePreview:
    """Clôture : crée le ticket de vente pour ce qui n'est pas revenu, fixe l'écart et la commission."""
    from app.controllers.sale_controller import BelowMinPriceError, CartLine, InsufficientStockError, PaymentLine, SaleController

    prev = preview_close(run_id, backs, prices, cash_received)
    with session_scope() as session:
        run = session.get(FieldRun, run_id)
        if run is None or run.status != RUN_OPEN:
            raise ValueError("Sortie introuvable ou déjà clôturée.")
        seller = session.get(FieldSeller, run.seller_id)
        seller_id = seller.id
    sale_id: Optional[int] = None
    sold_lines = [x for x in prev.lines if x.sold > EPS]
    if sold_lines:
        cart = []
        with session_scope() as session:
            for x in sold_lines:
                product = session.get(Product, x.product_id)
                cart.append(CartLine(product_id=x.product_id, name=x.name, unit_price=x.unit_price, quantity=x.sold,
                                     purchase_price=_f(product.purchase_price) if product else 0.0))
        cash_applied = min(prev.cash, prev.expected)
        payments = [PaymentLine("Espèces", cash_applied)] if cash_applied > 0 else []
        client_id = None
        discount = 0.0
        allow_credit = False
        if prev.shortage > EPS:
            if charge_shortage:
                with session_scope() as session:
                    client_id = _debt_client(session, session.get(FieldSeller, seller_id))
                allow_credit = True
            else:
                discount = prev.shortage            # perte supportée par l'entreprise : apparaît comme remise sur le ticket
        try:
            result = SaleController.create_sale(cart, payments, amount_received=cash_applied, discount=discount, client_id=client_id,
                                                user_id=user_id, allow_credit=allow_credit)
        except BelowMinPriceError as exc:
            raise ValueError(f"{exc}\n\nCorrigez les prix de vente, ou mettez le manque à la charge du vendeur.") from exc
        except InsufficientStockError as exc:
            raise ValueError(f"{exc}\n\nLe stock du dépôt a changé pendant la tournée : corrigez le stock avant de clôturer.") from exc
        sale_id = result.sale_id
    with session_scope() as session:
        run = session.execute(select(FieldRun).options(joinedload(FieldRun.lines)).where(FieldRun.id == run_id)).unique().scalar_one()
        by_id = {x.line_id: x for x in prev.lines}
        for l in run.lines:
            x = by_id[l.id]
            l.qty_back, l.unit_price, l.commission = x.qty_back, x.unit_price, round(x.commission * prev.factor, 3)
        run.status, run.closed_at = RUN_CLOSED, datetime.now()
        run.cash_received, run.expected, run.shortage = prev.cash, prev.expected, prev.shortage
        run.charged_to_seller = bool(charge_shortage and prev.shortage > EPS)
        run.commission, run.sale_id = prev.commission, sale_id
    return prev


# --- consultation ----------------------------------------------------------------------------------------------
@dataclass
class RunRow:
    id: int
    number: str
    seller: str
    seller_id: int
    status: str
    out_at: datetime
    closed_at: Optional[datetime]
    items: str
    expected: float
    cash: float
    shortage: float
    charged: bool
    commission: float
    commission_paid: bool


def list_runs(seller_id: Optional[int] = None, status: Optional[str] = None, start: Optional[datetime] = None,
              end: Optional[datetime] = None) -> List[RunRow]:
    with session_scope() as session:
        q = (select(FieldRun, FieldSeller.name).options(joinedload(FieldRun.lines)).join(FieldSeller, FieldSeller.id == FieldRun.seller_id)
             .order_by(FieldRun.id.desc()))
        if seller_id:
            q = q.where(FieldRun.seller_id == seller_id)
        if status:
            q = q.where(FieldRun.status == status)
        if start:
            q = q.where(FieldRun.out_at >= start)
        if end:
            q = q.where(FieldRun.out_at < end)
        return [RunRow(r.id, r.number, name, r.seller_id, r.status, r.out_at, r.closed_at,
                       ", ".join(f"{_f(l.qty_out):g}× {l.product_name}" for l in r.lines), _f(r.expected), _f(r.cash_received), _f(r.shortage),
                       bool(r.charged_to_seller), _f(r.commission), bool(r.commission_paid)) for r, name in session.execute(q).unique()]


def get_run_lines(run_id: int) -> List[FieldRunLine]:
    with session_scope() as session:
        rows = list(session.scalars(select(FieldRunLine).where(FieldRunLine.run_id == run_id).order_by(FieldRunLine.id)))
        session.expunge_all()
        return rows


def cancel_run(run_id: int) -> None:
    """Annule une sortie non clôturée (rien n'a été sorti du stock)."""
    with session_scope() as session:
        run = session.get(FieldRun, run_id)
        if run is None:
            return
        if run.status != RUN_OPEN:
            raise ValueError("Une sortie clôturée ne peut pas être annulée.")
        session.delete(run)


# --- commissions cumulées -----------------------------------------------------------------------------------------
@dataclass
class CommissionRow:
    seller_id: int
    seller: str
    runs: int
    gross: float
    debt: float


def commission_due(start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[CommissionRow]:
    """Commission non encore payée, par vendeur (sorties clôturées dans la période, fin exclue)."""
    with session_scope() as session:
        q = (select(FieldRun.seller_id, FieldSeller.name, func.count(), func.coalesce(func.sum(FieldRun.commission), 0))
             .join(FieldSeller, FieldSeller.id == FieldRun.seller_id)
             .where(FieldRun.status == RUN_CLOSED, FieldRun.commission_paid.is_(False)).group_by(FieldRun.seller_id, FieldSeller.name))
        if start:
            q = q.where(FieldRun.closed_at >= start)
        if end:
            q = q.where(FieldRun.closed_at < end)
        rows = [(sid, name, int(n), _f(total)) for sid, name, n, total in session.execute(q)]
    return sorted([CommissionRow(sid, name, n, total, seller_debt(sid)) for sid, name, n, total in rows], key=lambda r: r.seller.casefold())


def day_range(day: datetime) -> tuple:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def pay_commission(seller_id: int, start: Optional[datetime], end: Optional[datetime], *, deduct_debt: bool = False,
                   user_id: Optional[int] = None, username: str = "") -> FieldCommissionPayment:
    """Marque payées les commissions d'une période (un jour, un intervalle, N jours) ; peut retenir la dette du vendeur."""
    with session_scope() as session:
        q = select(FieldRun).where(FieldRun.seller_id == seller_id, FieldRun.status == RUN_CLOSED, FieldRun.commission_paid.is_(False))
        if start:
            q = q.where(FieldRun.closed_at >= start)
        if end:
            q = q.where(FieldRun.closed_at < end)
        runs = list(session.scalars(q))
        gross = round(sum(_f(r.commission) for r in runs), 3)
        if not runs or gross <= 0:
            raise ValueError("Aucune commission à payer pour ce vendeur sur cette période.")
        seller = session.get(FieldSeller, seller_id)
        seller_name, debt_client = seller.name, seller.debt_client_id
        first, last = min(r.closed_at for r in runs), max(r.closed_at for r in runs)
    if not user_id:
        raise ValueError("Utilisateur requis pour enregistrer le paiement d'une commission.")
    deducted = min(seller_debt(seller_id), gross) if (deduct_debt and debt_client) else 0.0
    net = round(gross - deducted, 3)
    from app.controllers.expense_controller import ExpenseController

    # La dépense d'abord (c'est elle qui peut être refusée) : rien d'autre n'est modifié si elle échoue.
    ExpenseController.create({"category": "Commissions vendeurs", "label": f"Commission {seller_name}", "amount": gross,
                              "notes": f"Du {first:%d/%m/%Y} au {last:%d/%m/%Y}" + (f" · dette déduite {deducted:g}" if deducted else "")}, user_id=user_id)
    if deducted > EPS:
        from app.controllers.client_controller import ClientController

        ClientController.settle_debt(debt_client, deducted, payment_method="Retenue sur commission",
                                     note=f"Déduit de la commission de {seller_name}", user_id=user_id, username=username)
    with session_scope() as session:
        now = datetime.now()
        for r in session.scalars(select(FieldRun).where(FieldRun.seller_id == seller_id, FieldRun.status == RUN_CLOSED,
                                                       FieldRun.commission_paid.is_(False),
                                                       *( [FieldRun.closed_at >= start] if start else []),
                                                       *( [FieldRun.closed_at < end] if end else []))):
            r.commission_paid, r.commission_paid_at = True, now
        pay = FieldCommissionPayment(seller_id=seller_id, date_from=first, date_to=last, gross=gross, debt_deducted=deducted, net_paid=net,
                                     runs=len(runs), paid_at=now)
        session.add(pay)
        session.flush()
        session.expunge(pay)
        return pay


def pay_last_days(seller_id: int, days: int, **kwargs) -> FieldCommissionPayment:
    """Paie les commissions des N derniers jours (aujourd'hui compris)."""
    if days < 1:
        raise ValueError("Le nombre de jours doit être d'au moins 1.")
    end = day_range(datetime.now())[1]
    return pay_commission(seller_id, end - timedelta(days=days), end, **kwargs)


# --- boutiques visitées -----------------------------------------------------------------------------------------------
def add_visit(run_id: int, shop: str, *, phone: str = "", area: str = "", result: str = "Vendu", amount: float = 0.0,
              follow_up: Optional[datetime] = None, note: str = "") -> int:
    shop = (shop or "").strip()
    if not shop:
        raise ValueError("Indiquez le nom de la boutique.")
    with session_scope() as session:
        if session.get(FieldRun, run_id) is None:
            raise ValueError("Sortie introuvable.")
        row = FieldVisit(run_id=run_id, shop=shop, phone=(phone or "").strip(), area=(area or "").strip(), result=result,
                         amount=max(0.0, to_float(amount)), follow_up=follow_up, note=(note or "").strip())
        session.add(row)
        session.flush()
        return row.id


def list_visits(run_id: int) -> List[FieldVisit]:
    with session_scope() as session:
        rows = list(session.scalars(select(FieldVisit).where(FieldVisit.run_id == run_id).order_by(FieldVisit.id)))
        session.expunge_all()
        return rows


@dataclass
class Prospect:
    shop: str
    phone: str
    area: str
    last_result: str
    last_visit: datetime
    follow_up: Optional[datetime]
    visits: int
    total: float


def prospects() -> List[Prospect]:
    """Boutiques regroupées par téléphone (ou nom) : dernier résultat, prochain rappel, total vendu."""
    with session_scope() as session:
        groups: dict = {}
        for v in session.scalars(select(FieldVisit).order_by(FieldVisit.created_at, FieldVisit.id)):
            key = (v.phone or "").replace(" ", "") or v.shop.casefold()
            g = groups.setdefault(key, {"shop": v.shop, "phone": v.phone, "area": v.area, "visits": 0, "total": 0.0})
            g.update(shop=v.shop, area=v.area or g["area"], phone=v.phone or g["phone"], last_result=v.result, last_visit=v.created_at,
                     follow_up=v.follow_up)
            g["visits"] += 1
            g["total"] += _f(v.amount)
        return sorted((Prospect(g["shop"], g["phone"], g["area"], g["last_result"], g["last_visit"], g["follow_up"], g["visits"], g["total"])
                       for g in groups.values()), key=lambda p: (p.follow_up is None, p.follow_up or p.last_visit))


# --- contacter le vendeur (WhatsApp) ---------------------------------------------------------------------------
def seller_message(seller_id: int) -> str:
    """Message prêt à envoyer : point sur la commission en cours et la dette éventuelle."""
    rows = [r for r in commission_due() if r.seller_id == seller_id]
    with session_scope() as session:
        seller = session.get(FieldSeller, seller_id)
        if seller is None:
            raise ValueError("Vendeur introuvable.")
        name = seller.name
    first = name.split()[0]
    if not rows:
        return f"Bonjour {first}, "
    r = rows[0]
    text = f"Bonjour {first}, votre commission à ce jour est de {r.gross:,.0f} F pour {r.runs} tournée(s).".replace(",", " ")
    if r.debt > 0:
        text += f" Il reste {r.debt:,.0f} F à régler sur vos manques.".replace(",", " ")
    return text


def seller_whatsapp_link(seller_id: int, text: str) -> str:
    from app.services import messaging_service

    with session_scope() as session:
        seller = session.get(FieldSeller, seller_id)
        phone = seller.phone if seller else ""
    if not (phone or "").strip():
        raise ValueError("Ce vendeur n'a pas de numéro de téléphone.")
    return messaging_service.whatsapp_link(phone, text)
