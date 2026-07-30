"""Recherche universelle (client, produit, facture, dette, fournisseur)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from sqlalchemy import or_, select

from app.database.connection import session_scope
from app.models.client import Client
from app.models.debt import Debt
from app.models.product import Product
from app.models.sale import Sale
from app.models.supplier import Supplier


@dataclass
class SearchHit:
    kind: str
    title: str
    subtitle: str
    entity_id: int


class SearchService:
    """Recherche cross-entité pour l'omnibox CRM."""

    @staticmethod
    def search(query: str, limit: int = 40) -> List[SearchHit]:
        q = (query or "").strip()
        if len(q) < 2:
            return []
        pattern = f"%{q}%"
        hits: List[SearchHit] = []
        with session_scope() as session:
            for client in session.scalars(
                select(Client)
                .where(
                    or_(
                        Client.name.ilike(pattern),
                        Client.phone.ilike(pattern),
                        Client.phone2.ilike(pattern),
                        Client.email.ilike(pattern),
                    )
                )
                .limit(10)
            ):
                hits.append(
                    SearchHit(
                        "client",
                        client.name,
                        f"{client.phone} {client.phone2}".strip(),
                        client.id,
                    )
                )
            for product in session.scalars(
                select(Product)
                .where(
                    or_(
                        Product.name.ilike(pattern),
                        Product.barcode.ilike(pattern),
                        Product.reference.ilike(pattern),
                    )
                )
                .limit(10)
            ):
                hits.append(
                    SearchHit(
                        "produit",
                        product.name,
                        f"Stock {float(product.quantity):g} — {float(product.sale_price):g}",
                        product.id,
                    )
                )
            for sale in session.scalars(
                select(Sale).where(Sale.ticket_number.ilike(pattern)).limit(10)
            ):
                hits.append(
                    SearchHit(
                        "facture",
                        sale.ticket_number,
                        f"{sale.status} — {float(sale.total):g}",
                        sale.id,
                    )
                )
            for supplier in session.scalars(
                select(Supplier)
                .where(
                    or_(
                        Supplier.name.ilike(pattern),
                        Supplier.phone.ilike(pattern),
                    )
                )
                .limit(10)
            ):
                hits.append(
                    SearchHit("fournisseur", supplier.name, supplier.phone, supplier.id)
                )
            for debt in session.scalars(
                select(Debt)
                .join(Client)
                .where(
                    or_(
                        Client.name.ilike(pattern),
                        Debt.note.ilike(pattern),
                        Debt.status.ilike(pattern),
                    )
                )
                .limit(10)
            ):
                hits.append(
                    SearchHit(
                        "dette",
                        f"Dette #{debt.id}",
                        f"Reste {float(debt.amount_remaining):g} — {debt.status}",
                        debt.id,
                    )
                )
        return hits[:limit]
