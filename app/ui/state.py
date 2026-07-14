"""État partagé de l'interface (utilisateur courant, thème)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.services import settings_service
from app.services.auth_service import AuthService


class AppState(QObject):
    """Contexte applicatif transmis aux pages de l'interface."""

    theme_changed = Signal(bool)
    data_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.auth = AuthService()
        self._dark = settings_service.get_setting("dark_mode", "0") == "1"

    @property
    def current_user(self):
        return self.auth.current_user

    @property
    def user_id(self):
        user = self.auth.current_user
        return user.id if user else None

    @property
    def is_admin(self) -> bool:
        return self.auth.require_admin()

    @property
    def dark(self) -> bool:
        return self._dark

    def set_dark(self, value: bool) -> None:
        self._dark = value
        settings_service.set_setting("dark_mode", "1" if value else "0")
        self.theme_changed.emit(value)

    def notify_data_changed(self) -> None:
        self.data_changed.emit()
