"""Contrôleur des fournisseurs (CRUD + recherche)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_, select

from app.database.connection import session_scope
from app.models.supplier import Supplier


class SupplierController:
    @staticmethod
    def list(search: str = "") -> List[Supplier]:
        with session_scope() as session:
            query = select(Supplier).order_by(Supplier.name)
            if search:
                pattern = f"%{search}%"
                query = query.where(
                    or_(Supplier.name.ilike(pattern), Supplier.phone.ilike(pattern))
                )
            rows = session.scalars(query).all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def get(supplier_id: int) -> Optional[Supplier]:
        with session_scope() as session:
            supplier = session.get(Supplier, supplier_id)
            if supplier:
                session.expunge(supplier)
            return supplier

    @staticmethod
    def create(data: dict) -> Supplier:
        with session_scope() as session:
            supplier = Supplier(
                name=str(data.get("name", "")).strip(),
                phone=str(data.get("phone", "")).strip(),
                address=str(data.get("address", "")).strip(),
                email=str(data.get("email", "")).strip(),
                notes=str(data.get("notes", "")).strip(),
            )
            session.add(supplier)
            session.flush()
            session.expunge(supplier)
            return supplier

    @staticmethod
    def update(supplier_id: int, data: dict) -> None:
        with session_scope() as session:
            supplier = session.get(Supplier, supplier_id)
            if not supplier:
                return
            supplier.name = str(data.get("name", supplier.name)).strip()
            supplier.phone = str(data.get("phone", supplier.phone)).strip()
            supplier.address = str(data.get("address", supplier.address)).strip()
            supplier.email = str(data.get("email", supplier.email)).strip()
            supplier.notes = str(data.get("notes", supplier.notes)).strip()

    @staticmethod
    def delete(supplier_id: int) -> None:
        with session_scope() as session:
            supplier = session.get(Supplier, supplier_id)
            if supplier:
                session.delete(supplier)
