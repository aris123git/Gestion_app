"""Service de sauvegarde et de restauration de la base de données.

La base SQLite étant un simple fichier, la sauvegarde consiste à copier ce
fichier de façon cohérente (via l'API de sauvegarde SQLite) vers le dossier de
sauvegardes horodaté.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List

from app import config


def create_backup(manual: bool = True) -> Path:
    """Crée une sauvegarde horodatée et retourne son chemin."""
    config.ensure_directories()
    tag = "manuelle" if manual else "auto"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = config.BACKUP_DIR / f"backup_{tag}_{timestamp}.db"

    # Utilise l'API de sauvegarde SQLite pour un instantané cohérent.
    source = sqlite3.connect(str(config.DATABASE_FILE))
    try:
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return destination


def list_backups() -> List[Path]:
    """Liste les sauvegardes existantes, de la plus récente à la plus ancienne."""
    if not config.BACKUP_DIR.exists():
        return []
    files = sorted(
        config.BACKUP_DIR.glob("backup_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files


def restore_backup(backup_path: str | Path) -> None:
    """Restaure la base à partir d'une sauvegarde (remplace le fichier courant)."""
    backup_path = Path(backup_path)
    if not backup_path.exists():
        raise FileNotFoundError(f"Sauvegarde introuvable : {backup_path}")

    # Sécurité : on sauvegarde l'état courant avant d'écraser.
    if config.DATABASE_FILE.exists():
        safety = config.BACKUP_DIR / "avant_restauration.db"
        shutil.copy2(config.DATABASE_FILE, safety)

    shutil.copy2(backup_path, config.DATABASE_FILE)
    # Nettoie les fichiers WAL/SHM éventuels qui deviendraient incohérents.
    for suffix in ("-wal", "-shm"):
        stale = Path(str(config.DATABASE_FILE) + suffix)
        if stale.exists():
            stale.unlink()


def auto_backup_if_needed(interval_hours: int = 12) -> Path | None:
    """Crée une sauvegarde automatique si la dernière est trop ancienne."""
    backups = [b for b in list_backups() if "auto" in b.name]
    if backups:
        last = datetime.fromtimestamp(backups[0].stat().st_mtime)
        if (datetime.now() - last).total_seconds() < interval_hours * 3600:
            return None
    return create_backup(manual=False)
