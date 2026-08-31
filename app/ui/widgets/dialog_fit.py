"""Utilitaires pour adapter les dialogues à l'écran disponible."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QWidget


def available_screen_size(widget: QWidget | None = None) -> tuple[int, int]:
    """Retourne (largeur, hauteur) utiles de l'écran concerné.

    Robuste avant ``show()`` (``windowHandle`` peut être ``None`` sous Windows)
    et si aucun écran n'est encore disponible.
    """
    screen = None
    try:
        if widget is not None:
            window = widget.window()
            handle = window.windowHandle() if window is not None else None
            if handle is not None:
                screen = handle.screen()
            if screen is None:
                # QWidget.screen() est sûr même sans handle natif.
                screen = widget.screen()
    except Exception:
        screen = None
    if screen is None:
        try:
            screen = QGuiApplication.primaryScreen()
        except Exception:
            screen = None
    if screen is None:
        return 1280, 720
    try:
        geo = screen.availableGeometry()
        return max(640, int(geo.width())), max(480, int(geo.height()))
    except Exception:
        return 1280, 720


def fit_dialog_to_screen(
    dialog: QDialog,
    *,
    min_width: int = 320,
    min_height: int = 240,
    preferred_width: int | None = None,
    preferred_height: int | None = None,
    max_width_ratio: float = 0.96,
    max_height_ratio: float = 0.92,
) -> None:
    """Borne min/max d'un dialogue pour qu'il tienne dans l'écran."""
    sw, sh = available_screen_size(dialog)
    max_w = max(min_width, int(sw * max_width_ratio))
    max_h = max(min_height, int(sh * max_height_ratio))
    dialog.setMinimumWidth(min(min_width, max_w))
    dialog.setMinimumHeight(min(min_height, max_h))
    dialog.setMaximumWidth(max_w)
    dialog.setMaximumHeight(max_h)
    if preferred_width is not None or preferred_height is not None:
        w = preferred_width or dialog.width()
        h = preferred_height or dialog.height()
        dialog.resize(min(w, max_w), min(h, max_h))
