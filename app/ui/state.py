"""État partagé de l'interface (utilisateur courant, thème, layout)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from app.services import settings_service
from app.services.auth_service import AuthService
from app.ui.responsive import LayoutEngine, LayoutProfile


class AppState(QObject):
    """Contexte applicatif transmis aux pages de l'interface."""

    theme_changed = Signal(bool)
    data_changed = Signal()
    layout_changed = Signal(object)  # LayoutProfile

    def __init__(self) -> None:
        super().__init__()
        self.auth = AuthService()
        self._dark = settings_service.get_setting("dark_mode", "0") == "1"
        self.layout_engine = LayoutEngine(self)
        self.layout_engine.changed.connect(self._on_layout_engine_changed)
        self._layout: Optional[LayoutProfile] = None

    def _on_layout_engine_changed(self, profile: LayoutProfile) -> None:
        self._layout = profile
        self.layout_changed.emit(profile)

    @property
    def layout(self) -> Optional[LayoutProfile]:
        return self._layout

    def update_viewport(self, width: int, height: int) -> LayoutProfile:
        """Point d'entrée unique pour le shell (MainWindow.resizeEvent)."""
        return self.layout_engine.update(width, height)

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

    def can(self, permission: str) -> bool:
        """Vérifie une permission du rôle de l'utilisateur connecté."""
        return self.auth.can(permission)

    @property
    def dark(self) -> bool:
        return self._dark

    def set_dark(self, value: bool) -> None:
        self._dark = value
        settings_service.set_setting("dark_mode", "1" if value else "0")
        self.theme_changed.emit(value)

    def notify_data_changed(self) -> None:
        self.data_changed.emit()
