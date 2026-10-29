"""Enlèvements : bon d'enlèvement fournisseur, livraisons aux clients (stations), écarts.

Cycle : brouillon → envoyé → validé (signé par le fournisseur ; le stock entre par un achat)
→ clôturé (le reste non livré devient une perte, ex. évaporation).
Le « reste à livrer » d'une ligne = quantité enlevée − quantités livrées (ventes non annulées).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app import config
from app.database.connection import session_scope
from app.models.pickup import (
    STATUS_CLOSED, STATUS_DRAFT, STATUS_SENT, STATUS_VALIDATED, Pickup, PickupDelivery, PickupItem,
)
from app.models.product import Product
from app.models.sale import Sale
from app.models.stock import MOVEMENT_OUT, StockMovement
from app.services import audit_service, settings_service
from app.services.invoice_numbering import format_number
from app.utils.helpers import to_float

COUNTER_KEY = "pickup_doc_counter"
LOSS_REASONS = ["Évaporation", "Jaugeage / écart de mesure", "Fuite / casse", "Autre"]
EPS = 0.0005


@dataclass
class PickupLine:
    product_id: int
    quantity: float
    unit_cost: float = 0.0


@dataclass
class Remaining:
    item_id: int
    product_id: int
    name: str
    picked: float
    delivered: float
    loss: float
    unit_cost: float

    @property
    def left(self) -> float:
        return round(max(0.0, self.picked - self.delivered - self.loss), 3)


def _f(v) -> float:
    return float(v or 0)


def _next_number(session) -> str:
    try:
        counter = int(settings_service.get_setting(COUNTER_KEY, "0") or 0)
    except ValueError:
        counter = 0
    numeric = [int(n) for n in session.scalars(select(Pickup.number)) if str(n).isdigit()]
    counter = max([counter, *numeric]) + 1
    settings_service.set_setting(COUNTER_KEY, str(counter))
    return format_number(counter)


def _fill_items(session, pickup: Pickup, lines: List[PickupLine]) -> None:
    if not lines:
        raise ValueError("Ajoutez au moins un produit à l'enlèvement.")
    pickup.items.clear()
    session.flush()
    for line in lines:
        qty = to_float(line.quantity)
        if qty <= 0:
            raise ValueError("Chaque produit doit avoir une quantité positive.")
        product = session.get(Product, line.product_id)
        if product is None:
            raise ValueError("Produit introuvable.")
        cost = to_float(line.unit_cost) or _f(product.purchase_price)
        pickup.items.append(PickupItem(
            product_id=product.id, product_name=product.name, quantity=qty, unit_cost=cost, line_total=round(qty * cost, 2),
        ))


def create(lines: List[PickupLine], *, supplier_id: Optional[int] = None, note: str = "", user_id: Optional[int] = None) -> int:
    with session_scope() as session:
        pickup = Pickup(number=_next_number(session), supplier_id=supplier_id, note=(note or "").strip(), user_id=user_id, status=STATUS_DRAFT)
        session.add(pickup)
        session.flush()
        _fill_items(session, pickup, lines)
        return pickup.id


def update_draft(pickup_id: int, lines: List[PickupLine], *, supplier_id: Optional[int], note: str = "") -> None:
    with session_scope() as session:
        pickup = session.get(Pickup, pickup_id)
        if pickup is None:
            raise ValueError("Enlèvement introuvable.")
        if pickup.status not in (STATUS_DRAFT, STATUS_SENT):
            raise ValueError("Un enlèvement validé ne peut plus être modifié.")
        pickup.supplier_id = supplier_id
        pickup.note = (note or "").strip()
        _fill_items(session, pickup, lines)


def delete_draft(pickup_id: int) -> None:
    with session_scope() as session:
        pickup = session.get(Pickup, pickup_id)
        if pickup is None:
            return
        if pickup.status not in (STATUS_DRAFT, STATUS_SENT):
            raise ValueError("Seul un enlèvement non validé peut être supprimé.")
        session.delete(pickup)


def mark_sent(pickup_id: int) -> None:
    with session_scope() as session:
        pickup = session.get(Pickup, pickup_id)
        if pickup is None:
            raise ValueError("Enlèvement introuvable.")
        if pickup.status != STATUS_DRAFT:
            raise ValueError("Seul un brouillon peut être marqué comme envoyé.")
        pickup.status = STATUS_SENT


def store_signed_file(pickup_id: int, source: str | Path) -> str:
    """Copie le scan / la photo du bon signé dans le dossier des données et retourne son chemin."""
    source = Path(source)
    if not source.is_file():
        raise ValueError("Fichier introuvable.")
    folder = config.DATA_DIR / "enlevements"
    folder.mkdir(parents=True, exist_ok=True)
    with session_scope() as session:
        pickup = session.get(Pickup, pickup_id)
        if pickup is None:
            raise ValueError("Enlèvement introuvable.")
        target = folder / f"BE_{pickup.number}_signe{source.suffix.lower()}"
        shutil.copy2(source, target)
        pickup.signed_file = str(target)
    return str(target)


def validate(pickup_id: int, *, amount_paid: float = 0, signed_file: str = "", user_id: Optional[int] = None, username: str = "") -> int:
    """Valide l'enlèvement : crée l'achat (le stock entre, la dette fournisseur est créée si non payé)."""
    from app.services.purchase_service import PurchaseLine, PurchaseService

    with session_scope() as session:
        pickup = session.execute(select(Pickup).options(joinedload(Pickup.items)).where(Pickup.id == pickup_id)).unique().scalar_one_or_none()
        if pickup is None:
            raise ValueError("Enlèvement introuvable.")
        if pickup.status not in (STATUS_DRAFT, STATUS_SENT):
            raise ValueError("Cet enlèvement est déjà validé.")
        if not pickup.supplier_id and to_float(amount_paid) < sum(_f(i.line_total) for i in pickup.items):
            raise ValueError("Choisissez le fournisseur (SONABHY…) pour enregistrer l'achat à crédit.")
        number, supplier_id = pickup.number, pickup.supplier_id
        lines = [PurchaseLine(i.product_id, i.product_name, _f(i.quantity), _f(i.unit_cost)) for i in pickup.items]
    purchase = PurchaseService.create(
        lines, supplier_id=supplier_id, invoice_number=f"BE-{number}", amount_paid=amount_paid,
        note=f"Enlèvement N° {number}", user_id=user_id, username=username,
    )
    with session_scope() as session:
        pickup = session.get(Pickup, pickup_id)
        pickup.status = STATUS_VALIDATED
        pickup.purchase_id = purchase.id
        pickup.validated_at = datetime.now()
    if signed_file:
        store_signed_file(pickup_id, signed_file)
    audit_service.log_action("Validation enlèvement", "Pickup", f"N° {number}", user_id, username)
    return purchase.id


def _delivered_by_item(session, pickup_id: int) -> dict[int, float]:
    rows = session.execute(
        select(PickupDelivery.pickup_item_id, func.coalesce(func.sum(PickupDelivery.quantity), 0))
        .join(Sale, Sale.id == PickupDelivery.sale_id)
        .join(PickupItem, PickupItem.id == PickupDelivery.pickup_item_id)
        .where(PickupItem.pickup_id == pickup_id, Sale.status == "completed")
        .group_by(PickupDelivery.pickup_item_id)
    ).all()
    return {i: _f(q) for i, q in rows}


def remaining(pickup_id: int) -> List[Remaining]:
    with session_scope() as session:
        pickup = session.execute(select(Pickup).options(joinedload(Pickup.items)).where(Pickup.id == pickup_id)).unique().scalar_one_or_none()
        if pickup is None:
            return []
        done = _delivered_by_item(session, pickup_id)
        return [Remaining(i.id, i.product_id, i.product_name, _f(i.quantity), done.get(i.id, 0.0), _f(i.loss_quantity), _f(i.unit_cost)) for i in pickup.items]


def link_sale(session, sale_id: int, links: list[tuple[int, float]]) -> None:
    """Rattache une vente (dans la transaction de la vente) à des lignes d'enlèvement.

    Refuse de livrer plus que le reste à livrer, ou depuis un enlèvement clôturé.
    On peut livrer avant la validation (le chauffeur emporte le bon d'enlèvement et le bon de livraison) :
    l'enlèvement se valide ensuite, quand le fournisseur a signé.
    """
    wanted: dict[int, float] = {}
    for item_id, qty in links:
        if to_float(qty) > 0:
            wanted[item_id] = wanted.get(item_id, 0.0) + to_float(qty)
    for item_id, qty in wanted.items():
        item = session.get(PickupItem, item_id)
        if item is None:
            raise ValueError("Ligne d'enlèvement introuvable.")
        pickup = session.get(Pickup, item.pickup_id)
        if pickup.status == STATUS_CLOSED:
            raise ValueError(f"L'enlèvement N° {pickup.number} est clôturé : livraison impossible.")
        done = _delivered_by_item(session, pickup.id).get(item_id, 0.0)
        left = _f(item.quantity) - done
        if qty > left + EPS:
            raise ValueError(f"« {item.product_name} » : il ne reste que {left:g} à livrer sur l'enlèvement N° {pickup.number} (demandé {qty:g}).")
        session.add(PickupDelivery(pickup_item_id=item_id, sale_id=sale_id, quantity=qty))


BEARER_CLIENT = "client"
BEARER_COMPANY = "company"


def default_bearer() -> str:
    """Qui supporte la perte (réglage) : le client par défaut."""
    return BEARER_COMPANY if settings_service.get_setting("pickup_loss_bearer", BEARER_CLIENT).strip() == BEARER_COMPANY else BEARER_CLIENT


@dataclass
class LossShare:
    client_id: int
    client_name: str
    item_id: int
    product_id: int
    name: str
    quantity: float
    unit_price: float


def loss_allocation(pickup_id: int) -> tuple[List[LossShare], List[tuple[str, float]]]:
    """Répartit le reste non livré entre les stations, au prorata de ce qu'elles ont reçu.

    Retourne (parts facturables, [(produit, quantité) impossibles à facturer : aucune livraison à un client]).
    """
    from app.models.client import Client
    from app.models.sale import SaleItem

    shares: List[LossShare] = []
    unbillable: List[tuple[str, float]] = []
    with session_scope() as session:
        pickup = session.execute(select(Pickup).options(joinedload(Pickup.items)).where(Pickup.id == pickup_id)).unique().scalar_one_or_none()
        if pickup is None:
            return [], []
        done = _delivered_by_item(session, pickup_id)
        for item in pickup.items:
            left = round(_f(item.quantity) - done.get(item.id, 0.0) - _f(item.loss_quantity), 3)
            if left <= EPS:
                continue
            rows = session.execute(
                select(Sale.client_id, Client.name, PickupDelivery.quantity, SaleItem.unit_price)
                .join(Sale, Sale.id == PickupDelivery.sale_id)
                .join(SaleItem, (SaleItem.sale_id == Sale.id) & (SaleItem.product_id == item.product_id))
                .join(Client, Client.id == Sale.client_id)
                .where(PickupDelivery.pickup_item_id == item.id, Sale.status == "completed", Sale.client_id.is_not(None))
            ).all()
            per: dict[int, list] = {}
            for cid, cname, q, price in rows:
                entry = per.setdefault(cid, [cname, 0.0, 0.0])
                entry[1] += _f(q)
                entry[2] += _f(q) * _f(price)
            total = sum(v[1] for v in per.values())
            if total <= EPS:
                unbillable.append((item.product_name, left))
                continue
            allocated, biggest = 0.0, max(per, key=lambda c: per[c][1])
            parts = {c: round(left * v[1] / total, 3) for c, v in per.items()}
            parts[biggest] = round(parts[biggest] + (left - sum(parts.values())), 3)  # le reste d'arrondi va à la plus grosse station
            for cid, qty in parts.items():
                if qty > EPS:
                    name, q, amount = per[cid]
                    shares.append(LossShare(cid, name, item.id, item.product_id, item.product_name, qty, round(amount / q, 3)))
    return shares, unbillable


def close(pickup_id: int, reason: str, *, bearer: Optional[str] = None, user_id: Optional[int] = None, username: str = "") -> float:
    """Clôture : le reste non livré est une perte (écart).

    ``bearer="client"`` : la perte est facturée aux stations, au prorata de leurs livraisons, au prix de leur
    livraison (vente à crédit) ; ``"company"`` : elle reste à la charge de l'entreprise (charge comptable).
    Retourne la valeur (au coût d'achat) de la perte supportée par l'entreprise.
    """
    from app import config
    from app.controllers.sale_controller import CartLine, PaymentLine, SaleController
    from app.services import price_layers

    reason = (reason or "").strip() or "Écart"
    bearer = bearer or default_bearer()
    with session_scope() as session:
        pickup = session.get(Pickup, pickup_id)
        if pickup is None:
            raise ValueError("Enlèvement introuvable.")
        if pickup.status != STATUS_VALIDATED:
            raise ValueError("Seul un enlèvement validé peut être clôturé.")
        number = pickup.number

    billed: dict[int, float] = {}
    if bearer == BEARER_CLIENT:
        shares, _unbillable = loss_allocation(pickup_id)
        by_client: dict[int, List[LossShare]] = {}
        for share in shares:
            by_client.setdefault(share.client_id, []).append(share)
        for client_id, parts in by_client.items():
            total = round(sum(p.quantity * p.unit_price for p in parts), 2)
            SaleController.create_sale(
                [CartLine(p.product_id, f"{p.name} (perte enlèvement {number})", p.unit_price, p.quantity) for p in parts],
                [PaymentLine(config.PAYMENT_METHOD_CREDIT, total)], client_id=client_id, user_id=user_id, allow_credit=True,
            )
            for p in parts:
                billed[p.item_id] = billed.get(p.item_id, 0.0) + p.quantity

    company_value = 0.0
    with session_scope() as session:
        pickup = session.execute(select(Pickup).options(joinedload(Pickup.items)).where(Pickup.id == pickup_id)).unique().scalar_one()
        done = _delivered_by_item(session, pickup_id)
        for item in pickup.items:
            left = round(_f(item.quantity) - done.get(item.id, 0.0), 3)
            if left <= EPS:
                continue
            item.loss_quantity = left
            share = min(left, billed.get(item.id, 0.0))
            item.billed_loss = share
            company_loss = round(left - share, 3)
            company_value += company_loss * _f(item.unit_cost)
            product = session.get(Product, item.product_id)
            if product and company_loss > EPS and not getattr(product, "sell_without_stock", False):
                before = _f(product.quantity)
                out = min(company_loss, max(before, 0.0))
                product.quantity = before - out
                price_layers.settle(session, product)
                session.add(StockMovement(
                    product_id=product.id, movement_type=MOVEMENT_OUT, quantity=out, quantity_before=before, quantity_after=before - out,
                    unit_cost=_f(item.unit_cost), reason=f"Perte enlèvement N° {number} ({reason})", user_id=user_id,
                ))
        pickup.status = STATUS_CLOSED
        pickup.closed_at = datetime.now()
        pickup.loss_reason = reason
        pickup.loss_bearer = bearer
    audit_service.log_action("Clôture enlèvement", "Pickup", f"N° {number} perte entreprise={company_value:g} facturée_clients={sum(billed.values()):g} ({reason})", user_id, username)
    return round(company_value, 2)


def tolerance_percent() -> float:
    try:
        return max(0.0, float(settings_service.get_setting("pickup_loss_tolerance", "0.5").replace(",", ".")))
    except ValueError:
        return 0.5


@dataclass
class PickupRow:
    id: int
    number: str
    date: datetime
    supplier: str
    status: str
    picked: float
    delivered: float
    loss: float
    total: float

    @property
    def left(self) -> float:
        return round(max(0.0, self.picked - self.delivered - self.loss), 3)

    @property
    def loss_percent(self) -> float:
        return round(self.loss / self.picked * 100, 2) if self.picked else 0.0

    @property
    def loss_alert(self) -> bool:
        return self.loss_percent > tolerance_percent()


def list_pickups(search: str = "", limit: int = 300) -> List[PickupRow]:
    with session_scope() as session:
        query = select(Pickup).options(joinedload(Pickup.items), joinedload(Pickup.supplier)).order_by(Pickup.date.desc()).limit(limit)
        rows = []
        for p in session.execute(query).unique().scalars():
            if search and search.lower() not in f"{p.number} {p.supplier.name if p.supplier else ''}".lower():
                continue
            done = _delivered_by_item(session, p.id)
            rows.append(PickupRow(
                p.id, p.number, p.date, p.supplier.name if p.supplier else "", p.status,
                sum(_f(i.quantity) for i in p.items), sum(done.values()), sum(_f(i.loss_quantity) for i in p.items), sum(_f(i.line_total) for i in p.items),
            ))
        return rows


def loss_report(start, end) -> list[tuple]:
    """Écarts par produit sur la période (enlèvements clôturés) : (produit, enlevé, perdu, % , valeur)."""
    lo = datetime.combine(start, datetime.min.time())
    hi = datetime.combine(end, datetime.max.time())
    out: dict[str, list[float]] = {}
    with session_scope() as session:
        for p in session.execute(select(Pickup).options(joinedload(Pickup.items)).where(Pickup.status == STATUS_CLOSED, Pickup.closed_at >= lo, Pickup.closed_at <= hi)).unique().scalars():
            for i in p.items:
                row = out.setdefault(i.product_name, [0.0, 0.0, 0.0])
                row[0] += _f(i.quantity)
                row[1] += _f(i.loss_quantity)
                row[2] += _f(i.loss_quantity) * _f(i.unit_cost)
    return sorted(((n, a, b, round(b / a * 100, 2) if a else 0.0, round(v, 2)) for n, (a, b, v) in out.items()), key=lambda r: r[4], reverse=True)


def delivered_sales(pickup_id: int) -> list[tuple]:
    """(n° ticket, date, client, produit, quantité) des livraisons de l'enlèvement."""
    from app.models.client import Client

    with session_scope() as session:
        rows = session.execute(
            select(Sale.ticket_number, Sale.date, Client.name, PickupItem.product_name, PickupDelivery.quantity, Sale.status)
            .join(Sale, Sale.id == PickupDelivery.sale_id)
            .join(PickupItem, PickupItem.id == PickupDelivery.pickup_item_id)
            .outerjoin(Client, Client.id == Sale.client_id)
            .where(PickupItem.pickup_id == pickup_id).order_by(Sale.date)
        ).all()
        return [(t, d, c or "", n, _f(q), s) for t, d, c, n, q, s in rows]
