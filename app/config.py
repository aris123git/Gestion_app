"""Configuration centrale de l'application.

Gère les chemins de stockage (base de données, sauvegardes, ressources) de
façon portable (Windows / Linux / macOS) et permet une surcharge via la
variable d'environnement ``GESTION_DATA_DIR`` (utile en développement et pour
les tests automatisés).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _default_data_dir() -> Path:
    """Retourne le dossier de données par défaut selon le système."""
    override = os.environ.get("GESTION_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", str(Path.home()))
        return Path(base) / "GestionCommerciale"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "GestionCommerciale"
    return Path.home() / ".local" / "share" / "GestionCommerciale"


# --- Chemins ---------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
ASSETS_DIR = BASE_DIR / "assets"

DATA_DIR = _default_data_dir()
BACKUP_DIR = DATA_DIR / "backups"
LOGO_DIR = DATA_DIR / "logos"
TICKET_DIR = DATA_DIR / "tickets"
EXPORT_DIR = DATA_DIR / "exports"

DATABASE_FILE = DATA_DIR / "gestion.db"


def ensure_directories() -> None:
    """Crée l'arborescence de stockage si nécessaire (idempotent)."""
    for directory in (DATA_DIR, BACKUP_DIR, LOGO_DIR, TICKET_DIR, EXPORT_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def database_url() -> str:
    """URL SQLAlchemy vers la base SQLite locale."""
    return f"sqlite:///{DATABASE_FILE}"


# --- Constantes métier -----------------------------------------------------
DEFAULT_UNITS = ["kg", "g", "carton", "pièce", "boîte", "sac", "litre", "bidon"]

PAYMENT_METHODS = [
    "Espèces",
    "Orange Money",
    "Moov Money",
    "Carte bancaire",
    "Virement",
]

EXPENSE_CATEGORIES = [
    "Loyer",
    "Salaire",
    "Transport",
    "Électricité",
    "Internet",
    "Autres",
]

ROLES = ["Administrateur", "Caissier"]
