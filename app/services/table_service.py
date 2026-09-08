"""Tables de salle — Maquis Caisse PC."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select

from app.database.connection import session_scope
from app.models.dining_table import (
    STATUS_FREE,
    STATUS_OCCUPIED,
    DiningTable,
)


class TableService:
    @staticmethod
    def list() -> List[DiningTable]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(DiningTable).order_by(
                        DiningTable.sort_order, DiningTable.id
                    )
                ).all()
            )
            for row in rows:
                session.expunge(row)
            return rows

    @staticmethod
    def create(
        *,
        number: str,
        name: str = "",
        capacity: int = 4,
    ) -> DiningTable:
        with session_scope() as session:
            table = DiningTable(
                number=(number or "").strip(),
                name=(name or "").strip(),
                capacity=max(1, int(capacity or 4)),
                status=STATUS_FREE,
            )
            session.add(table)
            session.flush()
            session.refresh(table)
            session.expunge(table)
            return table

    @staticmethod
    def set_status(table_id: int, status: str) -> DiningTable:
        with session_scope() as session:
            table = session.get(DiningTable, table_id)
            if not table:
                raise ValueError("Table introuvable.")
            table.status = status
            session.flush()
            session.refresh(table)
            session.expunge(table)
            return table

    @staticmethod
    def delete(table_id: int) -> None:
        with session_scope() as session:
            table = session.get(DiningTable, table_id)
            if table:
                session.delete(table)

    @staticmethod
    def ensure_defaults() -> None:
        """Crée 8 tables si aucune n'existe (1er lancement Maquis)."""
        with session_scope() as session:
            count = session.scalar(select(DiningTable.id).limit(1))
            if count is not None:
                return
            for i in range(1, 9):
                session.add(
                    DiningTable(
                        number=str(i),
                        name=f"Table {i}",
                        capacity=4,
                        status=STATUS_FREE,
                        sort_order=i,
                    )
                )
