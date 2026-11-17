"""Texte de commande fournisseur pour WhatsApp : liste courte, ou tableau aligné quand il y a beaucoup de produits."""
from __future__ import annotations

from typing import Sequence

from app.utils.helpers import format_quantity

TABLE_FROM = 6          # à partir de 6 produits : tableau
NAME_MAX = 26


def suggested_quantity(product) -> float:
    return max(2 * float(product.min_stock or 0) - float(product.quantity or 0), 1.0)


def products_to_order(supplier_id: int | None = None) -> list:
    """Produits actifs en rupture ou au minimum (ceux d'un fournisseur si précisé)."""
    from app.controllers.product_controller import ProductController
    out = []
    for p in ProductController.list(only_active=True):
        stock, minimum = float(p.quantity or 0), float(p.min_stock or 0)
        if not (stock <= 0 or (minimum > 0 and stock <= minimum)):
            continue
        if supplier_id is not None and getattr(p, 'supplier_id', None) != supplier_id:
            continue
        out.append(p)
    return out


def format_order(lines: Sequence[tuple[str, float]], intro: str = "Bonjour, je voudrais commander :") -> str:
    """lines : (produit, quantité). Moins de 6 lignes : phrase ; sinon tableau en police fixe (```)."""
    if len(lines) < TABLE_FROM:
        return intro + " " + ", ".join(f"{n} × {format_quantity(q)}" for n, q in lines) + "."
    names = [n if len(n) <= NAME_MAX else n[:NAME_MAX - 1] + "…" for n, _ in lines]
    qtys = [format_quantity(q) for _, q in lines]
    w = max(max(len(n) for n in names), len("Produit"))
    qw = max(max(len(q) for q in qtys), len("Qté"))
    rows = [f"{'Produit'.ljust(w)}  {'Qté'.rjust(qw)}", f"{'-' * w}  {'-' * qw}"]
    rows += [f"{n.ljust(w)}  {q.rjust(qw)}" for n, q in zip(names, qtys)]
    return intro + "\n```\n" + "\n".join(rows) + "\n```"
