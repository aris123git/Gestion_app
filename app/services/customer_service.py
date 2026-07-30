"""Service CRM clients (enrichissement fiche + stats d'achat)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.client import Client
from app.models.sale import Sale
from app.utils.helpers import format_datetime


class CustomerService:
    """Met à jour les indicateurs CRM d'un client."""

    @staticmethod
    def refresh_stats(client_id: int) -> None:
        with session_scope() as session:
            client = session.get(Client, client_id)
            if not client:
                return
            count = session.scalar(
                select(func.count())
                .select_from(Sale)
                .where(Sale.client_id == client_id, Sale.status == "completed")
            ) or 0
            last = session.scalar(
                select(func.max(Sale.date)).where(
                    Sale.client_id == client_id, Sale.status == "completed"
                )
            )
            client.purchase_count = int(count)
            client.last_visit = format_datetime(last) if last else ""

    @staticmethod
    def update_profile(client_id: int, data: dict) -> None:
        with session_scope() as session:
            client = session.get(Client, client_id)
            if not client:
                return
            if "name" in data:
                client.name = str(data["name"]).strip()
            if "phone" in data:
                client.phone = str(data["phone"]).strip()
            if "phone2" in data:
                client.phone2 = str(data["phone2"]).strip()
            if "address" in data:
                client.address = str(data["address"]).strip()
            if "email" in data:
                client.email = str(data["email"]).strip()
            if "notes" in data:
                client.notes = str(data["notes"]).strip()

    @staticmethod
    def mark_visit(client_id: Optional[int], when: Optional[datetime] = None) -> None:
        if not client_id:
            return
        when = when or datetime.now()
        with session_scope() as session:
            client = session.get(Client, client_id)
            if client:
                client.last_visit = format_datetime(when)
                client.purchase_count = int(client.purchase_count or 0) + 1
