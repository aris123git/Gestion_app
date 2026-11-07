"""Relance automatique de l'application (ferme la fenêtre actuelle, démarre une nouvelle instance)."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def relaunch_command() -> tuple[str, list[str]]:
    """Programme et arguments pour relancer : l'exe lui-même une fois installé, sinon l'interpréteur + le script."""
    if getattr(sys, "frozen", False):
        return sys.executable, list(sys.argv[1:])
    return sys.executable, list(sys.argv)


def relaunch_application() -> None:
    program, args = relaunch_command()
    if not QProcess.startDetached(program, args):
        logger.error("Relance automatique impossible (%s) : l'utilisateur devra rouvrir le logiciel.", program)
    app = QApplication.instance()
    if app is not None:
        app.quit()
    else:
        QApplication.quit()
