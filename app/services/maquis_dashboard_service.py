"""Tableau de bord Maquis — agrégats sur commandes (parité app mobile)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app import config
from app.database.connection import session_scope
from app.models.expense import Expense
from app.models.open_order import STATUS_CANCELLED, STATUS_OPEN, STATUS_PAID, STATUS_UNPAID, OpenOrder
from app.models.open_order_payment import OpenOrderPayment
from app.models.product import Product
from app.services.cash_session_service import CashSessionService


@dataclass
class WaitressStatsRow:
    waitress_id: Optional[int]
    waitress_name: str
    order_count: int
    paid_count: int
    unpaid_count: int
    ca_generated: float
    ca_collected: float
    to_collect: float


@dataclass
class ProductSalesRow:
    product_name: str
    quantity: float
    revenue: float
    cost: float

    @property
    def benefice(self) -> float:
        return self.revenue - self.cost


@dataclass
class CaisseDuJour:
    cash_today: float
    mobile_today: float
    debt_today: float
    avoir_today: float = 0.0
    fond_de_caisse: Optional[float] = None
    especes_theoriques: Optional[float] = None
    ecart: Optional[float] = None


@dataclass
class MaquisDashboardStats:
    orders_count: int
    open_orders: int
    ca_generated: float
    ca_collected: float
    to_collect: float
    cost_of_goods: float
    benefice: float
    expenses_total: float
    top_products: List[ProductSalesRow] = field(default_factory=list)
    waitress_stats: List[WaitressStatsRow] = field(default_factory=list)
    caisse_du_jour: CaisseDuJour = field(default_factory=lambda: CaisseDuJour(0, 0, 0))


def _today_bounds() -> Tuple[datetime, datetime]:
    now = datetime.now()
    start = datetime.combine(now.date(), time.min)
    end = datetime.combine(now.date(), time.max)
    return start, end


def _month_bounds() -> Tuple[datetime, datetime]:
    now = datetime.now()
    start = datetime(now.year, now.month, 1)
    end = datetime.combine(now.date(), time.max)
    return start, end


_CASH_LABELS = frozenset({"Espèces", "CASH", "cash"})
_MOBILE_LABELS = frozenset(
    {
        "Orange Money",
        "ORANGE_MONEY",
        "Moov Money",
        "MOOV_MONEY",
        "Wave",
        "WAVE",
        "Carte bancaire",
        "CARD",
        "Autre",
        "OTHER",
        "Mobile Money",
        "MOBILE_MONEY",
    }
)
_DEBT_LABELS = frozenset({config.PAYMENT_METHOD_CREDIT, "Dette", "DEBT"})


def _is_open_status(status: str) -> bool:
    return status in (STATUS_OPEN, STATUS_UNPAID, "EN_COURS", "NON_PAYEE")


def _is_paid_status(status: str) -> bool:
    return status in (STATUS_PAID, "PAYEE")


def _orders_between(session, start: datetime, end: datetime) -> List[OpenOrder]:
    rows = list(
        session.scalars(
            select(OpenOrder)
            .options(joinedload(OpenOrder.items), joinedload(OpenOrder.payments))
            .where(
                OpenOrder.created_at >= start,
                OpenOrder.created_at <= end,
                OpenOrder.status != STATUS_CANCELLED,
            )
        )
        .unique()
        .all()
    )
    return rows


def _debt_paid_on_order(order: OpenOrder) -> float:
    total = 0.0
    for p in order.payments or []:
        mode = str(p.payment_mode or "")
        if mode in _DEBT_LABELS:
            total += float(p.amount or 0)
    return total


def _product_cost(session, product_id: Optional[int], qty: float) -> float:
    if not product_id:
        return 0.0
    product = session.get(Product, product_id)
    if not product:
        return 0.0
    return float(product.purchase_price or 0) * qty


def _product_sales(orders: List[OpenOrder], session) -> List[ProductSalesRow]:
    rows: dict[str, ProductSalesRow] = {}
    for order in orders:
        if not _is_paid_status(order.status):
            continue
        debt = _debt_paid_on_order(order)
        total = float(order.total or 0)
        fraction = 1.0
        if total > 0 and debt > 0:
            fraction = max(0.0, min(1.0, (total - debt) / total))
        for item in order.items or []:
            name = item.product_name or "?"
            qty = float(item.quantity or 0)
            rev = float(item.line_total or 0) * fraction
            cost = _product_cost(session, item.product_id, qty) * fraction
            prev = rows.get(name)
            if prev:
                rows[name] = ProductSalesRow(
                    name, prev.quantity + qty, prev.revenue + rev, prev.cost + cost
                )
            else:
                rows[name] = ProductSalesRow(name, qty, rev, cost)
    return sorted(rows.values(), key=lambda r: r.revenue, reverse=True)


def _waitress_stats(orders: List[OpenOrder]) -> List[WaitressStatsRow]:
    groups: dict[tuple, list] = {}
    for o in orders:
        key = (o.waitress_id, (o.waitress_name or "Sans serveuse").strip() or "Sans serveuse")
        groups.setdefault(key, []).append(o)
    out: List[WaitressStatsRow] = []
    for (wid, wname), lst in groups.items():
        paid = [o for o in lst if _is_paid_status(o.status)]
        debt_sum = sum(_debt_paid_on_order(o) for o in paid)
        generated = sum(float(o.total or 0) for o in paid) - debt_sum
        collected = sum(float(o.paid_amount or 0) for o in paid) - debt_sum
        to_collect = sum(float(o.remaining_amount) for o in lst)
        out.append(
            WaitressStatsRow(
                waitress_id=wid,
                waitress_name=wname,
                order_count=len(lst),
                paid_count=len(paid),
                unpaid_count=sum(1 for o in lst if _is_open_status(o.status)),
                ca_generated=max(0.0, generated),
                ca_collected=max(0.0, collected),
                to_collect=max(0.0, to_collect),
            )
        )
    out.sort(key=lambda r: r.ca_generated, reverse=True)
    return out


def _payments_between(session, start: datetime, end: datetime) -> List[OpenOrderPayment]:
    return list(
        session.scalars(
            select(OpenOrderPayment).where(
                OpenOrderPayment.created_at >= start,
                OpenOrderPayment.created_at <= end,
            )
        ).all()
    )


def _caisse_du_jour(session, start: datetime, end: datetime, user_id: Optional[int]) -> CaisseDuJour:
    cash = 0.0
    mobile = 0.0
    debt = 0.0
    for p in _payments_between(session, start, end):
        mode = str(p.payment_mode or "")
        amt = float(p.amount or 0)
        if mode in _CASH_LABELS:
            cash += amt
        elif mode in _DEBT_LABELS:
            debt += amt
        elif mode in _MOBILE_LABELS or mode == "Mixte":
            mobile += amt
        else:
            mobile += amt
    fond = None
    theorique = None
    ecart = None
    if user_id:
        sess = CashSessionService.get_open(user_id)
        if sess:
            fond = float(sess.opening_float or 0)
            cash_open = 0.0
            for p in _payments_between(session, sess.opened_at or start, end):
                if str(p.payment_mode or "") in _CASH_LABELS:
                    cash_open += float(p.amount or 0)
            theorique = fond + cash_open
            if sess.closing_counted is not None and theorique is not None:
                ecart = float(sess.closing_counted) - theorique
    return CaisseDuJour(
        cash_today=cash,
        mobile_today=mobile,
        debt_today=debt,
        fond_de_caisse=fond,
        especes_theoriques=theorique,
        ecart=ecart,
    )


def dashboard_stats(
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    user_id: Optional[int] = None,
) -> MaquisDashboardStats:
    if start is None or end is None:
        start, end = _today_bounds()
    with session_scope() as session:
        orders = _orders_between(session, start, end)
        paid = [o for o in orders if _is_paid_status(o.status)]
        open_count = sum(1 for o in orders if _is_open_status(o.status))
        debt_on_orders = sum(_debt_paid_on_order(o) for o in paid)
        sales_ca = sum(float(o.total or 0) for o in paid) - debt_on_orders
        sales_collected = sum(float(o.paid_amount or 0) for o in paid) - debt_on_orders
        to_collect = sum(float(o.remaining_amount) for o in orders if _is_open_status(o.status))
        products = _product_sales(orders, session)
        cost = sum(p.cost for p in products)
        expenses = float(
            session.scalar(
                select(func.coalesce(func.sum(Expense.amount), 0)).where(
                    Expense.date >= start,
                    Expense.date <= end,
                )
            )
            or 0
        )
        caisse = _caisse_du_jour(session, start, end, user_id)
        return MaquisDashboardStats(
            orders_count=len(orders),
            open_orders=open_count,
            ca_generated=max(0.0, sales_ca - expenses),
            ca_collected=max(0.0, sales_collected - expenses),
            to_collect=max(0.0, to_collect),
            cost_of_goods=cost,
            benefice=max(0.0, sales_ca - cost - expenses),
            expenses_total=expenses,
            top_products=products[:8],
            waitress_stats=_waitress_stats(orders),
            caisse_du_jour=caisse,
        )


def today_stats(user_id: Optional[int] = None) -> MaquisDashboardStats:
    start, end = _today_bounds()
    return dashboard_stats(start=start, end=end, user_id=user_id)


def month_stats(user_id: Optional[int] = None) -> MaquisDashboardStats:
    start, end = _month_bounds()
    return dashboard_stats(start=start, end=end, user_id=user_id)
