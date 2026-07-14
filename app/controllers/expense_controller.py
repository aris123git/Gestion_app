"""Contrôleur des dépenses."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.expense import Expense
from app.utils.helpers import to_float


class ExpenseController:
    @staticmethod
    def list(
        start: Optional[date] = None,
        end: Optional[date] = None,
        limit: int = 500,
    ) -> List[Expense]:
        with session_scope() as session:
            query = select(Expense)
            if start:
                query = query.where(
                    Expense.date >= datetime.combine(start, datetime.min.time())
                )
            if end:
                query = query.where(
                    Expense.date <= datetime.combine(end, datetime.max.time())
                )
            query = query.order_by(Expense.date.desc()).limit(limit)
            rows = session.scalars(query).all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def create(data: dict, user_id: Optional[int] = None) -> Expense:
        with session_scope() as session:
            expense = Expense(
                category=str(data.get("category", "Autres")),
                label=str(data.get("label", "")).strip(),
                amount=to_float(data.get("amount")),
                date=data.get("date") or datetime.now(),
                notes=str(data.get("notes", "")).strip(),
                user_id=user_id,
            )
            session.add(expense)
            session.flush()
            session.expunge(expense)
            return expense

    @staticmethod
    def update(expense_id: int, data: dict) -> None:
        with session_scope() as session:
            expense = session.get(Expense, expense_id)
            if not expense:
                return
            expense.category = str(data.get("category", expense.category))
            expense.label = str(data.get("label", expense.label)).strip()
            expense.amount = to_float(data.get("amount"))
            if data.get("date"):
                expense.date = data["date"]
            expense.notes = str(data.get("notes", expense.notes)).strip()

    @staticmethod
    def delete(expense_id: int) -> None:
        with session_scope() as session:
            expense = session.get(Expense, expense_id)
            if expense:
                session.delete(expense)

    @staticmethod
    def total_between(start: date, end: date) -> float:
        with session_scope() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(Expense.amount), 0)).where(
                    Expense.date >= datetime.combine(start, datetime.min.time()),
                    Expense.date <= datetime.combine(end, datetime.max.time()),
                )
            )
            return float(total or 0)
