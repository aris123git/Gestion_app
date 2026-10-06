"""Mise à l'échelle proportionnelle de toute l'interface selon la taille d'écran.

Principe : l'application est dessinée pour un écran de référence (22″ en
1920×1080). Sur un écran plus petit (ex. portable 15″ en 1366×768), TOUTE
l'interface (polices, boutons, marges, tableaux) est réduite dans la même
proportion, comme une photo qu'on rétrécit : rien ne disparaît, rien n'est
déformé. Sur un écran plus grand, tout est agrandi de la même façon.

Doit être appelé AVANT la création de ``QApplication``.

Réglage manuel (optionnel) :
- variable d'environnement ``QT_SCALE_FACTOR`` (ex. 0.8) : prioritaire ;
- ou fichier ``ui_scale.txt`` dans le dossier de données de l'application,
  contenant ``auto`` (défaut), ``off`` ou un nombre (ex. ``0.85``).
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

# Écran de référence : 22″ Full HD (hauteur utile ≈ 1040 px hors barre des tâches).
REF_WIDTH = 1920
REF_HEIGHT = 1040
# Bornes de sécurité (en dessous, le texte devient illisible).
MIN_SCALE = 0.60
MAX_SCALE = 1.50


def compute_scale(width: int, height: int) -> float:
    """Facteur d'échelle pour un écran ``width × height`` (pixels logiques)."""
    if width <= 0 or height <= 0:
        return 1.0
    scale = min(width / REF_WIDTH, height / REF_HEIGHT)
    # Entre 0,96 et 1,04 on ne touche à rien (évite un flou inutile).
    if 0.96 <= scale <= 1.04:
        return 1.0
    scale = max(MIN_SCALE, min(MAX_SCALE, scale))
    return round(scale, 2)


def _screen_size_windows() -> tuple[int, int]:
    """Résolution logique de l'écran principal (avant création de Qt)."""
    import ctypes

    user32 = ctypes.windll.user32
    return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


def _read_override() -> str:
    try:
        from app import config

        path = config.DATA_DIR / "ui_scale.txt"
        if path.exists():
            return path.read_text(encoding="utf-8").strip().lower()
    except Exception:
        logger.debug("Lecture ui_scale.txt impossible.", exc_info=True)
    return "auto"


def apply_ui_scale() -> float:
    """Définit ``QT_SCALE_FACTOR`` selon l'écran. Retourne le facteur appliqué."""
    if os.environ.get("QT_SCALE_FACTOR"):
        return float(os.environ["QT_SCALE_FACTOR"] or 1.0)
    mode = _read_override()
    if mode == "off":
        return 1.0
    try:
        if mode != "auto":
            scale = max(MIN_SCALE, min(MAX_SCALE, float(mode.replace(",", "."))))
        elif sys.platform.startswith("win"):
            scale = compute_scale(*_screen_size_windows())
        else:
            return 1.0
    except Exception:
        logger.debug("Calcul de l'échelle impossible.", exc_info=True)
        return 1.0
    if scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(scale)
    logger.info("Échelle interface : %s", scale)
    return scale
  
