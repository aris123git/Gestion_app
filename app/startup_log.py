"""Journalisation des crashes de démarrage (EXE Windows ``console=False``).

Écrit ``startup_error.log`` dans le dossier de données
(``%APPDATA%/GestionCommerciale`` ou ``GESTION_DATA_DIR``).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def startup_error_log_path() -> Path:
    """Chemin du fichier de trace (best-effort)."""
    try:
        from app import config

        config.ensure_directories()
        return Path(config.DATA_DIR) / "startup_error.log"
    except Exception:
        return Path.home() / "GestionCommerciale_startup_error.log"


def write_startup_error(exc: BaseException | None = None, *, note: str = "") -> None:
    """Écrit une trace d'erreur de démarrage (jamais bloquant)."""
    try:
        path = startup_error_log_path()
        parts: list[str] = []
        if note:
            parts.append(note.rstrip() + "\n")
        if exc is not None:
            parts.append(
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            )
        else:
            parts.append("".join(traceback.format_exception(*sys.exc_info())))
        path.write_text("".join(parts), encoding="utf-8")
    except Exception:
        pass


def install_startup_excepthook() -> None:
    """Installe un ``sys.excepthook`` qui journalise dans ``startup_error.log``."""
    previous = sys.excepthook

    def _hook(exc_type, exc, tb) -> None:
        try:
            path = startup_error_log_path()
            path.write_text(
                "".join(traceback.format_exception(exc_type, exc, tb)),
                encoding="utf-8",
            )
        except Exception:
            pass
        previous(exc_type, exc, tb)

    sys.excepthook = _hook
