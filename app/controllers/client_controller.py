"""Contrôleur des clients (CRUD, recherche, gestion des dettes)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_, select

from app.database.connection import session_scope
from app.models.client import Client
from app.models.sale import Sale
from app.utils.helpers import to_float


class ClientController:
    @staticmethod
    def list(search: str = "") -> List[Client]:
        with session_scope() as session:
            query = select(Client).order_by(Client.name)
            if search:
                pattern = f"%{search}%"
                query = query.where(
                    or_(Client.name.ilike(pattern), Client.phone.ilike(pattern))
                )
            rows = session.scalars(query).all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def get(client_id: int) -> Optional[Client]:
        with session_scope() as session:
            client = session.get(Client, client_id)
            if client:
                session.expunge(client)
            return client

    @staticmethod
    def create(data: dict) -> Client:
        with session_scope() as session:
            client = Client(
                name=str(data.get("name", "")).strip(),
                phone=str(data.get("phone", "")).strip(),
                address=str(data.get("address", "")).strip(),
                email=str(data.get("email", "")).strip(),
                debt=to_float(data.get("debt")),
                notes=str(data.get("notes", "")).strip(),
            )
            session.add(client)
            session.flush()
            session.expunge(client)
            return client

    @staticmethod
    def update(client_id: int, data: dict) -> None:
        with session_scope() as session:
            client = session.get(Client, client_id)
            if not client:
                return
            client.name = str(data.get("name", client.name)).strip()
            client.phone = str(data.get("phone", client.phone)).strip()
            client.address = str(data.get("address", client.address)).strip()
            client.email = str(data.get("email", client.email)).strip()
            client.notes = str(data.get("notes", client.notes)).strip()
            if "debt" in data:
                client.debt = to_float(data.get("debt"))

    @staticmethod
    def delete(client_id: int) -> None:
        with session_scope() as session:
            client = session.get(Client, client_id)
            if client:
                session.delete(client)

    @staticmethod
    def add_debt(client_id: int, amount: float) -> None:
        with session_scope() as session:
            client = session.get(Client, client_id)
            if client:
                client.debt = float(client.debt) + to_float(amount)

    @staticmethod
    def settle_debt(client_id: int, amount: float) -> None:
        """Enregistre un remboursement de dette (borné à zéro)."""
        with session_scope() as session:
            client = session.get(Client, client_id)
            if client:
                client.debt = max(0.0, float(client.debt) - to_float(amount))

    @staticmethod
    def history(client_id: int) -> List[Sale]:
        with session_scope() as session:
            rows = session.scalars(
                select(Sale)
                .where(Sale.client_id == client_id)
                .order_by(Sale.date.desc())
            ).all()
            session.expunge_all()
            return list(rows)
