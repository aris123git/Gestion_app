"""Service d'authentification et de gestion des utilisateurs."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.user import User
from app.services import audit_service
from app.utils.security import hash_password, verify_password


class AuthService:
    """Gère la connexion et le compte courant de la session."""

    def __init__(self) -> None:
        self._current_user: Optional[User] = None

    # --- Session -----------------------------------------------------------
    @property
    def current_user(self) -> Optional[User]:
        return self._current_user

    def login(self, username: str, password: str) -> Optional[User]:
        """Valide les identifiants et ouvre la session si corrects."""
        with session_scope() as session:
            user = session.scalar(
                select(User).where(func.lower(User.username) == username.lower())
            )
            if not user or not user.is_active:
                return None
            if not verify_password(password, user.password_hash):
                return None
            session.expunge(user)
            self._current_user = user
            audit_service.log_action(
                "Connexion", "User", f"{user.username}", user.id, user.username
            )
            return user

    def logout(self) -> None:
        if self._current_user:
            audit_service.log_action(
                "Déconnexion",
                "User",
                self._current_user.username,
                self._current_user.id,
                self._current_user.username,
            )
        self._current_user = None

    def require_admin(self) -> bool:
        return bool(self._current_user and self._current_user.is_admin)

    # --- CRUD utilisateurs -------------------------------------------------
    @staticmethod
    def count_users() -> int:
        with session_scope() as session:
            return session.scalar(select(func.count()).select_from(User)) or 0

    @staticmethod
    def list_users() -> List[User]:
        with session_scope() as session:
            rows = session.scalars(select(User).order_by(User.username)).all()
            session.expunge_all()
            return list(rows)

    @staticmethod
    def create_user(
        username: str,
        password: str,
        full_name: str = "",
        role: str = "Caissier",
    ) -> User:
        with session_scope() as session:
            user = User(
                username=username.strip(),
                full_name=full_name.strip(),
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
            session.add(user)
            session.flush()
            session.expunge(user)
            return user

    @staticmethod
    def update_user(
        user_id: int,
        full_name: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        password: Optional[str] = None,
    ) -> None:
        with session_scope() as session:
            user = session.get(User, user_id)
            if not user:
                return
            if full_name is not None:
                user.full_name = full_name.strip()
            if role is not None:
                user.role = role
            if is_active is not None:
                user.is_active = is_active
            if password:
                user.password_hash = hash_password(password)

    @staticmethod
    def delete_user(user_id: int) -> None:
        with session_scope() as session:
            user = session.get(User, user_id)
            if user:
                session.delete(user)
