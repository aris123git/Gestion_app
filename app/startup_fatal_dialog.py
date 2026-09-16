"""Affiche une erreur de démarrage à l'écran (EXE Windows sans console)."""

from __future__ import annotations

import sys
import textwrap


def show_startup_fatal(message: str) -> None:
    if not getattr(sys, "frozen", False):
        return
    body = textwrap.dedent(message).strip()
    if len(body) > 3500:
        body = body[:3500] + "\n…\n(Voir startup_error.log pour la trace complète.)"
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0,
                body,
                "NexaGes — erreur au démarrage",
                0x00000010,  # MB_ICONERROR
            )
            return
        except Exception:
            pass
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, "NexaGes", body)
        app.processEvents()
    except Exception:
        pass
