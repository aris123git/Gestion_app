"""Couches de prix (FIFO) : le nouveau prix s'applique après l'écoulement de l'ancien stock.

Principe : ``product.purchase_price`` / ``product.sale_price`` sont les prix des
unités les plus anciennes. Les lots arrivés avec un autre prix attendent dans
``PriceLayer`` ; quand les unités plus anciennes sont toutes vendues, le lot le
plus ancien devient le prix courant du produit.

Unités au prix courant = quantité en stock − somme des unités des lots en attente.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.price_layer import PriceLayer
from app.models.product import Product

EPS = 0.0005


def _f(value) -> float:
    return float(value or 0)


def pending_layers(session, product_id: int) -> list[PriceLayer]:
    return list(session.scalars(
        select(PriceLayer).where(PriceLayer.product_id == product_id).order_by(PriceLayer.created_at, PriceLayer.id)
    ).all())


def current_units(product: Product, layers: list[PriceLayer]) -> float:
    """Unités encore au prix courant du produit (les plus anciennes)."""
    return _f(product.quantity) - sum(_f(l.remaining) for l in layers)


def _tracked(product: Product) -> bool:
    return not getattr(product, "sell_without_stock", False)


def effective_prices(product: Product, layers: list[PriceLayer]) -> tuple[float, float]:
    """Derniers prix connus (ceux du dernier lot en attente, sinon ceux du produit)."""
    cost, sale = _f(product.purchase_price), _f(product.sale_price)
    for layer in layers:
        cost = _f(layer.purchase_price)
        if layer.sale_price is not None:
            sale = _f(layer.sale_price)
    return cost, sale


def register_arrival(session, product: Product, before_qty: float, qty: float, cost: float, sale_price: float | None = None, source: str = "") -> bool:
    """Enregistre l'arrivée de ``qty`` unités à ``cost`` (et ``sale_price`` éventuel).

    Retourne True si les prix sont mis en attente (ancien stock restant), False
    s'ils sont appliqués tout de suite. À appeler APRÈS ``product.quantity`` mis à jour
    n'est pas nécessaire : ``before_qty`` est la quantité avant l'arrivée.
    """
    cost = _f(cost)
    sale = _f(sale_price) if sale_price else None
    if cost <= 0 and sale is None:
        return False
    layers = pending_layers(session, product.id)
    old_units = before_qty - sum(_f(l.remaining) for l in layers)
    last_cost, last_sale = effective_prices(product, layers)
    cost_changed = cost > 0 and abs(cost - last_cost) >= EPS
    sale_changed = sale is not None and abs(sale - last_sale) >= EPS

    if not _tracked(product) or (old_units <= EPS and not layers):
        # Plus d'ancien stock : les nouveaux prix s'appliquent immédiatement.
        if cost > 0:
            product.purchase_price = cost
        if sale is not None:
            product.sale_price = sale
        return False
    if not cost_changed and not sale_changed:
        if layers:  # mêmes prix que le dernier lot : les unités le rejoignent
            layers[-1].remaining = _f(layers[-1].remaining) + qty
        return bool(layers)
    session.add(PriceLayer(
        product_id=product.id, remaining=qty,
        purchase_price=cost if cost > 0 else last_cost,
        sale_price=sale if sale is not None else None, source=source,
    ))
    session.flush()
    return True


def schedule_price_change(session, product: Product, purchase_price: float | None, sale_price: float | None, source: str = "Fiche produit") -> bool:
    """Programme un changement de prix sans nouvelles unités (appliqué après l'ancien stock)."""
    layers = pending_layers(session, product.id)
    if not _tracked(product) or current_units(product, layers) <= EPS:
        return False
    last_cost, _last_sale = effective_prices(product, layers)
    session.add(PriceLayer(
        product_id=product.id, remaining=0,
        purchase_price=_f(purchase_price) if purchase_price else last_cost,
        sale_price=_f(sale_price) if sale_price else None, source=source,
    ))
    session.flush()
    return True


def settle(session, product: Product) -> None:
    """Après une baisse de stock : applique les prix du lot suivant si l'ancien stock est épuisé."""
    if product is None or not product.id:
        return
    layers = pending_layers(session, product.id)
    while layers and current_units(product, layers) <= EPS:
        layer = layers.pop(0)
        if _f(layer.purchase_price) > 0:
            product.purchase_price = _f(layer.purchase_price)
        if layer.sale_price is not None:
            product.sale_price = _f(layer.sale_price)
        session.delete(layer)
        session.flush()


def fifo_cost(session, product: Product, qty: float) -> float | None:
    """Coût unitaire moyen pondéré de ``qty`` unités vendues (None s'il n'y a pas de lot en attente)."""
    layers = pending_layers(session, product.id)
    if not layers or qty <= 0:
        return None
    remaining = qty
    total = 0.0
    take = min(remaining, max(0.0, current_units(product, layers)))
    total += take * _f(product.purchase_price)
    remaining -= take
    for layer in layers:
        if remaining <= EPS:
            break
        take = min(remaining, _f(layer.remaining))
        total += take * _f(layer.purchase_price)
        remaining -= take
    if remaining > EPS:  # hors lots connus : dernier coût
        total += remaining * _f(layers[-1].purchase_price)
    return round(total / qty, 3)


def summary(session, product_id: int) -> list[tuple[float, float, float | None]]:
    """[(unités, prix d'achat, prix de vente)] des lots en attente (pour l'affichage)."""
    return [(_f(l.remaining), _f(l.purchase_price), None if l.sale_price is None else _f(l.sale_price)) for l in pending_layers(session, product_id)]
