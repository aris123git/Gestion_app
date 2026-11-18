"""Texte de commande fournisseur pour WhatsApp : liste courte, ou tableau aligné quand il y a beaucoup de produits."""
from __future__ import annotations

from typing import Sequence

from app.utils.helpers import format_quantity

PDF_FROM = 6          # à partir de 6 produits : la liste part en PDF


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
    """lines : (produit, quantité) → « intro Riz × 8, Huile × 6. »"""
    return intro + " " + ", ".join(f"{n} × {format_quantity(q)}" for n, q in lines) + "."


def pdf_intro(count: int, intro: str = "Bonjour, voici ma commande") -> str:
    return f"{intro} ({count} produits) en pièce jointe."
