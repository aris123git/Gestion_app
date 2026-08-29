"""Service d'authentification et de gestion des utilisateurs."""

from __future__ import annotations

import time
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database.connection import session_scope
from app.models.user import User
from app.services import audit_service
from app.utils.security import hash_password, validate_password, verify_password

_MAX_LOGIN_FAILURES = 5
_LOGIN_BLOCK_SECONDS = 60


class AuthService:
    """Gère la connexion et le compte courant de la session."""

    def __init__(self) -> None:
        self._current_user: Optional[User] = None
        self._login_failures: dict[str, int] = {}
        self._blocked_until: dict[str, float] = {}

    # --- Session -----------------------------------------------------------
    @property
    def current_user(self) -> Optional[User]:
        return self._current_user

    def login(self, username: str, password: str) -> Optional[User]:
        """Valide les identifiants et ouvre la session si corrects."""
        username = username.strip()
        key = username.lower()
        self._raise_if_blocked(key)
        with session_scope() as session:
            user = session.scalar(
                select(User).where(func.lower(User.username) == key)
            )
            if not user or not user.is_active:
                self._record_login_failure(key)
                return None
            if not verify_password(password, user.password_hash):
                self._record_login_failure(key)
                return None
            session.expunge(user)
            self._current_user = user
            self._clear_login_failures(key)
            audit_service.log_action(
                "Connexion", "User", f"{user.username}", user.id, user.username
            )
            return user

    def _raise_if_blocked(self, key: str) -> None:
        blocked_until = self._blocked_until.get(key, 0)
        now = time.monotonic()
        if blocked_until <= now:
            if blocked_until:
                self._blocked_until.pop(key, None)
                self._login_failures.pop(key, None)
            return
        remaining = int(blocked_until - now) + 1
        raise ValueError(f"Trop de tentatives. Réessayez dans {remaining} secondes.")

    def _record_login_failure(self, key: str) -> None:
        failures = self._login_failures.get(key, 0) + 1
        if failures >= _MAX_LOGIN_FAILURES:
            self._login_failures[key] = 0
            self._blocked_until[key] = time.monotonic() + _LOGIN_BLOCK_SECONDS
            return
        self._login_failures[key] = failures

    def _clear_login_failures(self, key: str) -> None:
        self._login_failures.pop(key, None)
        self._blocked_until.pop(key, None)

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

    def refresh_current_user(self) -> Optional[User]:
        """Recharge l'utilisateur courant afin de refléter les changements de rôle."""
        if not self._current_user:
            return None
        user_id = self._current_user.id
        with session_scope() as session:
            user = session.get(User, user_id)
            if not user or not user.is_active:
                self._current_user = None
                return None
            session.expunge(user)
            self._current_user = user
            return user

    reload_current_user = refresh_current_user

    def require_admin(self) -> bool:
        return bool(self._current_user and self._current_user.is_admin)

    def can(self, permission: str) -> bool:
        """Vérifie une permission du rôle de l'utilisateur connecté."""
        from app.services import permissions as perms

        return perms.can(self._current_user, permission)

    @staticmethod
    def verify_admin_password(username: str, password: str) -> bool:
        """Valide les identifiants d'un compte Administrateur actif."""
        from app.services import permissions as perms

        with session_scope() as session:
            user = session.scalar(
                select(User).where(func.lower(User.username) == username.lower())
            )
            if not user or not user.is_active:
                return False
            if user.role != perms.ROLE_ADMIN:
                return False
            return verify_password(password, user.password_hash)

    @staticmethod
    def verify_any_admin_password(password: str) -> bool:
        """Valide un mot de passe contre n'importe quel Administrateur actif."""
        return AuthService.identify_admin_by_password(password) is not None

    @staticmethod
    def identify_admin_by_password(password: str) -> Optional[tuple[int, str]]:
        """Retourne ``(id, username)`` du premier admin dont le MDP correspond."""
        from app.services import permissions as perms

        if not password:
            return None
        with session_scope() as session:
            admins = session.scalars(
                select(User).where(
                    User.role == perms.ROLE_ADMIN,
                    User.is_active.is_(True),
                )
            ).all()
            for admin in admins:
                if verify_password(password, admin.password_hash):
                    return int(admin.id), str(admin.username)
        return None

    @staticmethod
    def default_admin_uses_default_password() -> bool:
        """Indique si le compte admin actif utilise encore admin/admin."""
        with session_scope() as session:
            user = session.scalar(
                select(User).where(func.lower(User.username) == "admin")
            )
            return bool(
                user
                and user.is_active
                and verify_password("admin", user.password_hash)
            )

    # --- CRUD utilisateurs -------------------------------------------------
    @staticmethod
    def count_users() -> int:
        with session_scope() as session:
            return session.scalar(select(func.count()).select_from(User)) or 0

    @staticmethod
    def count_admins(active_only: bool = True) -> int:
        from app.services import permissions as perms

        with session_scope() as session:
            stmt = (
                select(func.count())
                .select_from(User)
                .where(User.role == perms.ROLE_ADMIN)
            )
            if active_only:
                stmt = stmt.where(User.is_active.is_(True))
            return session.scalar(stmt) or 0

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
        *,
        audit_user_id: Optional[int] = None,
        audit_username: str = "",
    ) -> User:
        username = username.strip()
        if not username:
            raise ValueError("Le nom d'utilisateur est obligatoire.")
        validate_password(password)
        with session_scope() as session:
            existing = session.scalar(
                select(User).where(func.lower(User.username) == username.lower())
            )
            if existing:
                raise ValueError("Ce nom d'utilisateur existe déjà.")
            user = User(
                username=username,
                full_name=full_name.strip(),
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
            session.add(user)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ValueError("Ce nom d'utilisateur existe déjà.") from exc
            session.expunge(user)
        audit_service.log_action(
            "Création utilisateur",
            "User",
            f"{user.username} ({user.role})",
            audit_user_id,
            audit_username,
        )
        return user

    @staticmethod
    def update_user(
        user_id: int,
        full_name: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        password: Optional[str] = None,
        *,
        audit_user_id: Optional[int] = None,
        audit_username: str = "",
    ) -> None:
        if password is not None:
            validate_password(password)
        target_username = ""
        target_role = ""
        target_active = None
        password_changed = password is not None
        with session_scope() as session:
            user = session.get(User, user_id)
            if not user:
                return
            AuthService._ensure_not_last_admin_change(session, user, role, is_active)
            if full_name is not None:
                user.full_name = full_name.strip()
            if role is not None:
                user.role = role
            if is_active is not None:
                user.is_active = is_active
            if password is not None:
                user.password_hash = hash_password(password)
            target_username = user.username
            target_role = user.role
            target_active = user.is_active
        audit_service.log_action(
            "Modification utilisateur",
            "User",
            (
                f"{target_username} ({target_role}) "
                f"actif={'oui' if target_active else 'non'} "
                f"mot_de_passe={'modifié' if password_changed else 'inchangé'}"
            ),
            audit_user_id,
            audit_username,
        )

    @staticmethod
    def delete_user(
        user_id: int,
        *,
        audit_user_id: Optional[int] = None,
        audit_username: str = "",
    ) -> None:
        target = ""
        with session_scope() as session:
            user = session.get(User, user_id)
            if user:
                AuthService._ensure_not_last_admin_delete(session, user)
                target = f"{user.username} ({user.role})"
                session.delete(user)
        if target:
            audit_service.log_action(
                "Suppression utilisateur",
                "User",
                target,
                audit_user_id,
                audit_username,
            )

    @staticmethod
    def _active_admin_count(session) -> int:
        from app.services import permissions as perms

        return session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == perms.ROLE_ADMIN, User.is_active.is_(True))
        ) or 0

    @staticmethod
    def _ensure_not_last_admin_change(
        session, user: User, role: Optional[str], is_active: Optional[bool]
    ) -> None:
        from app.services import permissions as perms

        target_role = role if role is not None else user.role
        target_active = is_active if is_active is not None else user.is_active
        removes_active_admin = (
            user.role == perms.ROLE_ADMIN
            and user.is_active
            and (target_role != perms.ROLE_ADMIN or not target_active)
        )
        if removes_active_admin and AuthService._active_admin_count(session) <= 1:
            raise ValueError(
                "Impossible de retirer ou désactiver le dernier administrateur actif."
            )

    @staticmethod
    def _ensure_not_last_admin_delete(session, user: User) -> None:
        from app.services import permissions as perms

        if (
            user.role == perms.ROLE_ADMIN
            and user.is_active
            and AuthService._active_admin_count(session) <= 1
        ):
            raise ValueError("Impossible de supprimer le dernier administrateur actif.")
