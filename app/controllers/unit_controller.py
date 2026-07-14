"""Contrôleur des unités de mesure."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select

from app.database.connection import session_scope
from app.models.unit import Unit


class UnitController:
    @staticmethod
    def list() -> List[Unit]:
        with session_scope() as session:
            rows = session.scalars(select(Unit).order_by(Unit.name)).all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def create(name: str) -> Optional[Unit]:
        name = name.strip()
        if not name:
            return None
        with session_scope() as session:
            existing = session.scalar(select(Unit).where(Unit.name == name))
            if existing:
                session.expunge(existing)
                return existing
            unit = Unit(name=name, is_default=False)
            session.add(unit)
            session.flush()
            session.expunge(unit)
            return unit

    @staticmethod
    def delete(unit_id: int) -> None:
        with session_scope() as session:
            unit = session.get(Unit, unit_id)
            if unit and not unit.is_default:
                session.delete(unit)
