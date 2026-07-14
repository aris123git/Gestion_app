"""Orchestration de l'interface : thème, premier démarrage, connexion, fenêtre.

Gère aussi le cycle de connexion/déconnexion (retour à l'écran de login sans
quitter l'application).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QApplication

from app.database.connection import init_database
from app.database.seed import seed_all
from app.services import backup_service
from app.ui.login_dialog import LoginDialog
from app.ui.main_window import MainWindow
from app.ui.setup_wizard import SetupWizard
from app.ui.state import AppState
from app.ui.theme import apply_theme

_controller: Optional["AppController"] = None


class AppController:
    """Contrôleur de haut niveau du cycle de vie de l'interface."""

    def __init__(self, app: QApplication):
        self.app = app
        self.state = AppState()
        self.window: Optional[MainWindow] = None
        self.state.theme_changed.connect(self._on_theme_changed)
        apply_theme(self.app, self.state.dark)

    def _on_theme_changed(self, dark: bool) -> None:
        apply_theme(self.app, dark)

    def run_first_start_if_needed(self) -> None:
        from app.services import settings_service

        if not settings_service.is_configured():
            wizard = SetupWizard()
            wizard.exec()
            # On s'assure que la fenêtre de l'assistant est bien détruite avant
            # d'ouvrir la connexion (évite tout conflit de focus sur certains
            # gestionnaires de fenêtres).
            wizard.deleteLater()
            self.app.processEvents()

    def show_login(self) -> bool:
        """Affiche la connexion. Retourne True si l'utilisateur s'est connecté."""
        dialog = LoginDialog(self.state)
        return bool(dialog.exec())

    def show_main(self) -> None:
        self.window = MainWindow(self.state)
        self.window.show()

    def restart_login(self) -> None:
        """Après déconnexion : réaffiche la connexion puis la fenêtre."""
        if self.show_login():
            self.show_main()
        else:
            self.app.quit()


def restart_login() -> None:
    """Point d'entrée module-level utilisé par la fenêtre principale."""
    if _controller is not None:
        _controller.restart_login()


def run() -> int:
    """Démarre l'application complète et retourne le code de sortie."""
    global _controller

    init_database()
    seed_all()
    try:
        backup_service.auto_backup_if_needed()
    except Exception:
        pass  # Une sauvegarde automatique ne doit jamais bloquer le démarrage.

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Gestion Commerciale")

    _controller = AppController(app)
    _controller.run_first_start_if_needed()

    if not _controller.show_login():
        return 0

    _controller.show_main()
    return app.exec()
