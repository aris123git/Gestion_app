"""Contrôleur des clients (CRUD, recherche).

La gestion des dettes (création, remboursement, cache) est déléguée à
``DebtService`` — source de vérité métier.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_, select

from app.database.connection import session_scope
from app.models.client import Client
from app.models.sale import Sale
from app.services.debt_service import DebtService
from app.utils.helpers import to_float


class ClientController:
    @staticmethod
    def list(search: str = "") -> List[Client]:
        with session_scope() as session:
            query = select(Client).order_by(Client.name)
            if search:
                pattern = f"%{search}%"
                query = query.where(
                    or_(
                        Client.name.ilike(pattern),
                        Client.phone.ilike(pattern),
                        Client.phone2.ilike(pattern),
                    )
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
    def find_by_phone(phone: str) -> Optional[Client]:
        """Retrouve un client par téléphone (correspondance exacte prioritaire)."""
        phone = str(phone or "").strip()
        if not phone:
            return None
        with session_scope() as session:
            # Exact sur phone / phone2, puis recherche partielle.
            client = session.scalar(
                select(Client)
                .where(or_(Client.phone == phone, Client.phone2 == phone))
                .order_by(Client.name)
                .limit(1)
            )
            if client is None:
                pattern = f"%{phone}%"
                client = session.scalar(
                    select(Client)
                    .where(
                        or_(Client.phone.ilike(pattern), Client.phone2.ilike(pattern))
                    )
                    .order_by(Client.name)
                    .limit(1)
                )
            if client:
                session.expunge(client)
            return client

    @staticmethod
    def find_or_create_by_phone(
        phone: str,
        name: str = "",
        user_id: Optional[int] = None,
        username: str = "",
    ) -> Optional[Client]:
        """Retrouve ou crée un client à partir d'un numéro de téléphone."""
        phone = str(phone or "").strip()
        if not phone:
            return None
        existing = ClientController.find_by_phone(phone)
        if existing:
            return existing
        display = str(name or "").strip() or f"Client {phone}"
        return ClientController.create(
            {"name": display, "phone": phone},
            user_id=user_id,
            username=username,
        )

    @staticmethod
    def create(
        data: dict,
        user_id: Optional[int] = None,
        username: str = "",
    ) -> Client:
        opening_debt = to_float(data.get("debt"))
        with session_scope() as session:
            client = Client(
                name=str(data.get("name", "")).strip(),
                phone=str(data.get("phone", "")).strip(),
                phone2=str(data.get("phone2", "")).strip(),
                address=str(data.get("address", "")).strip(),
                email=str(data.get("email", "")).strip(),
                debt=0,
                notes=str(data.get("notes", "")).strip(),
            )
            session.add(client)
            session.flush()
            client_id = client.id
        if opening_debt > 0:
            DebtService.create_debt(
                client_id,
                opening_debt,
                note="Solde d'ouverture",
                user_id=user_id,
                username=username,
            )
        return ClientController.get(client_id)  # type: ignore[return-value]

    @staticmethod
    def update(client_id: int, data: dict) -> None:
        """Met à jour la fiche client.

        Le champ ``debt`` du formulaire est ignoré : le solde est un cache
        géré exclusivement par ``DebtService``.
        """
        with session_scope() as session:
            client = session.get(Client, client_id)
            if not client:
                return
            client.name = str(data.get("name", client.name)).strip()
            client.phone = str(data.get("phone", client.phone)).strip()
            client.phone2 = str(data.get("phone2", getattr(client, "phone2", ""))).strip()
            client.address = str(data.get("address", client.address)).strip()
            client.email = str(data.get("email", client.email)).strip()
            client.notes = str(data.get("notes", client.notes)).strip()

    @staticmethod
    def delete(client_id: int) -> None:
        with session_scope() as session:
            client = session.get(Client, client_id)
            if client:
                session.delete(client)

    @staticmethod
    def add_debt(
        client_id: int,
        amount: float,
        *,
        note: str = "",
        due_date=None,
        user_id: Optional[int] = None,
        username: str = "",
    ) -> None:
        """Crée une dette manuelle (hors vente)."""
        DebtService.create_debt(
            client_id,
            amount,
            due_date=due_date,
            note=note or "Dette manuelle",
            user_id=user_id,
            username=username,
        )

    @staticmethod
    def settle_debt(
        client_id: int,
        amount: float,
        *,
        payment_method: str = "Espèces",
        note: str = "",
        user_id: Optional[int] = None,
        username: str = "",
    ) -> None:
        """Enregistre un remboursement (répartition FIFO sur les dettes actives)."""
        DebtService.pay_client(
            client_id,
            amount,
            payment_method=payment_method,
            note=note,
            user_id=user_id,
            username=username,
        )

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
