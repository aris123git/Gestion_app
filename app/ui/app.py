"""Orchestration de l'interface : thème, produit, activation, connexion, fenêtre.

Gère aussi le cycle de connexion/déconnexion (retour à l'écran de login sans
quitter l'application).
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtWidgets import QApplication

from app.database.connection import init_database
from app.database.seed import seed_all
from app.services import activation_service, backup_service, product_profile
from app.startup_log import install_startup_excepthook, write_startup_error
from app.ui.activation_dialog import ActivationDialog
from app.ui.login_dialog import LoginDialog
from app.ui.main_window import MainWindow
from app.ui.product_choice_dialog import ProductChoiceDialog
from app.ui.setup_wizard import SetupWizard
from app.ui.state import AppState
from app.ui.theme import apply_theme

logger = logging.getLogger(__name__)

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

    def ensure_product_chosen(self) -> bool:
        """Sur nouvel ordinateur : choix Gestion App / Maquis Caisse."""
        if product_profile.is_product_chosen():
            return True
        # Migration : déjà activé (fichier activation.dat) sans profil → Gestion App.
        from app.services.activation_service import ACTIVATION_FILE

        if ACTIVATION_FILE.exists():
            product_profile.set_product(product_profile.PRODUCT_GESTION)
            return True
        dialog = ProductChoiceDialog()
        dialog.exec()
        ok = bool(dialog.selected)
        dialog.deleteLater()
        self.app.processEvents()
        return ok

    def ensure_activated(self) -> bool:
        """Affiche l'activation au premier démarrage. Retourne True si activé."""
        if activation_service.is_activated():
            return True
        dialog = ActivationDialog()
        dialog.exec()
        if dialog.activated:
            dialog.deleteLater()
            self.app.processEvents()
            return True
        return False

    def run_first_start_if_needed(self) -> bool:
        from app.services import settings_service

        if not settings_service.is_configured():
            wizard = SetupWizard()
            wizard.exec()
            wizard.deleteLater()
            self.app.processEvents()
            return settings_service.is_configured()
        return True

    def show_login(self) -> bool:
        dialog = LoginDialog(self.state)
        return bool(dialog.exec())

    def show_main(self) -> None:
        if product_profile.is_maquis():
            try:
                from app.services.table_service import TableService

                TableService.ensure_defaults()
            except Exception:
                logger.exception("Initialisation tables Maquis impossible")
        self.window = MainWindow(self.state)
        self.window.showMaximized()
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self.window._publish_viewport)

    def restart_login(self) -> None:
        if self.show_login():
            self.show_main()
        else:
            self.app.quit()


def restart_login() -> None:
    if _controller is not None:
        _controller.restart_login()


def run() -> int:
    """Démarre l'application complète et retourne le code de sortie."""
    global _controller

    install_startup_excepthook()

    try:
        init_database()
        seed_all()
        try:
            backup_service.run_startup_auto_backup()
        except Exception:
            logger.exception("Échec de la sauvegarde automatique au démarrage.")

        # Charge la langue UI (fr / en / zh) avant de construire les écrans.
        from app.i18n import get_language

        get_language()

        app = QApplication.instance() or QApplication([])
        app.setApplicationName(product_profile.PARENT_NAME)
        app.setOrganizationName(product_profile.PARENT_VENDOR)

        _controller = AppController(app)

        # 1) Nouveau PC → choix produit  2) Activation  3) Commerce  4) Login
        if not _controller.ensure_product_chosen():
            return 0
        if not _controller.ensure_activated():
            return 0
        if not _controller.run_first_start_if_needed():
            return 0
        if not _controller.show_login():
            return 0

        _controller.show_main()
        return app.exec()
    except Exception as exc:
        write_startup_error(exc, note="Échec fatal au démarrage de NexaGes.")
        logger.exception("Échec fatal au démarrage.")
        raise
