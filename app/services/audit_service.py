"""Service de journalisation des actions importantes."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select

from app.database.connection import session_scope
from app.models.audit import AuditLog


def log_action(
    action: str,
    entity: str = "",
    details: str = "",
    user_id: Optional[int] = None,
    username: str = "",
) -> None:
    """Enregistre une action dans le journal d'audit."""
    with session_scope() as session:
        session.add(
            AuditLog(
                action=action,
                entity=entity,
                details=details,
                user_id=user_id,
                username=username,
            )
        )


def list_logs(limit: int = 500, start=None, end=None) -> List[AuditLog]:
    """Retourne les derniers enregistrements du journal, sur une période optionnelle."""
    from datetime import datetime, time
    with session_scope() as session:
        query = select(AuditLog).order_by(AuditLog.date.desc())
        if start is not None:
            query = query.where(AuditLog.date >= datetime.combine(start, time.min))
        if end is not None:
            query = query.where(AuditLog.date <= datetime.combine(end, time.max))
        rows = session.scalars(query.limit(limit)).all()
        session.expunge_all()
        return list(rows)
