"""Service de sauvegarde et de restauration complète (niveau professionnel).

Une sauvegarde est un fichier **ZIP horodaté** contenant :

```
gestion.db          # instantané cohérent de la base SQLite
logos/              # logos importés
tickets/            # tickets générés
exports/            # exports PDF / Excel
manifest.json       # métadonnées (version, date, contenu) pour l'intégrité
```

Fonctionnalités :
- création d'une sauvegarde complète (dossier géré ou emplacement choisi) ;
- restauration (avec sauvegarde de sécurité automatique préalable) ;
- vérification d'intégrité (ZIP valide + base SQLite saine) ;
- suppression automatique des anciennes sauvegardes (rétention configurable) ;
- sauvegarde automatique selon une fréquence (quotidienne / hebdo / mensuelle).

Tous les chemins reposent sur ``pathlib`` et sur les constantes de ``config``
(``DATA_DIR``, ``BACKUP_DIR``, ``DATABASE_FILE``, ...).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from app import __version__, config

# Dossiers de données inclus dans chaque sauvegarde (nom relatif -> chemin).
_DATA_FOLDERS = {
    "logos": config.LOGO_DIR,
    "tickets": config.TICKET_DIR,
    "exports": config.EXPORT_DIR,
}

_DB_ARCNAME = "gestion.db"
_MANIFEST_ARCNAME = "manifest.json"
_BACKUP_PREFIX = "Sauvegarde"
_SAFETY_PREFIX = "Securite_avant_restauration"

# Clés de préférences (stockées via settings_service).
SETTING_AUTO_ENABLED = "auto_backup_enabled"
SETTING_AUTO_FREQUENCY = "auto_backup_frequency"
SETTING_RETENTION = "backup_retention"
SETTING_LAST_PATH = "last_backup_path"

DEFAULT_RETENTION = 10
FREQUENCIES = ["quotidienne", "hebdomadaire", "mensuelle"]
_FREQUENCY_DELTA = {
    "quotidienne": timedelta(days=1),
    "hebdomadaire": timedelta(weeks=1),
    "mensuelle": timedelta(days=30),
}


class BackupError(Exception):
    """Erreur générique liée aux opérations de sauvegarde/restauration."""


@dataclass
class BackupInfo:
    """Métadonnées pratiques d'un fichier de sauvegarde."""

    path: Path
    created_at: datetime
    size_bytes: int

    @property
    def size_human(self) -> str:
        size = float(self.size_bytes)
        for unit in ("o", "Ko", "Mo", "Go"):
            if size < 1024 or unit == "Go":
                return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{self.size_bytes} o"


# --- Utilitaires internes --------------------------------------------------
def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _unique_zip_path(directory: Path, prefix: str) -> Path:
    """Retourne un chemin de fichier ZIP unique (évite les collisions <1 s)."""
    base = f"{prefix}_{_timestamp()}"
    candidate = directory / f"{base}.zip"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{base}_{counter}.zip"
        counter += 1
    return candidate


def _snapshot_database(destination: Path) -> None:
    """Copie cohérente de la base SQLite (API backup) vers ``destination``.

    L'API de sauvegarde SQLite garantit un instantané cohérent même si la base
    est en cours d'utilisation (journalisation WAL incluse).
    """
    source = sqlite3.connect(str(config.DATABASE_FILE))
    try:
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _add_folder_to_zip(archive: zipfile.ZipFile, arc_root: str, folder: Path) -> None:
    """Ajoute récursivement le contenu d'un dossier dans l'archive."""
    if not folder.exists():
        return
    for item in sorted(folder.rglob("*")):
        if item.is_file():
            arcname = f"{arc_root}/{item.relative_to(folder).as_posix()}"
            archive.write(item, arcname)


# --- Création --------------------------------------------------------------
def create_full_backup(
    destination_dir: str | Path | None = None,
    manual: bool = True,
    prefix: str = _BACKUP_PREFIX,
) -> Path:
    """Crée une sauvegarde complète (ZIP) et retourne son chemin.

    - ``destination_dir`` : dossier de destination. Si ``None``, la sauvegarde est
      créée dans ``config.BACKUP_DIR`` (dossier géré, soumis à la rétention).
    - ``prefix`` : préfixe du nom de fichier.
    """
    config.ensure_directories()
    target_dir = Path(destination_dir) if destination_dir else config.BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    zip_path = _unique_zip_path(target_dir, prefix)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            db_snapshot = Path(tmp) / _DB_ARCNAME
            _snapshot_database(db_snapshot)

            manifest = {
                "app": "Gestion Commerciale",
                "version": __version__,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "type": "manuelle" if manual else "automatique",
                "contents": [_DB_ARCNAME, *(_DATA_FOLDERS.keys())],
            }

            with zipfile.ZipFile(
                zip_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.write(db_snapshot, _DB_ARCNAME)
                for arc_root, folder in _DATA_FOLDERS.items():
                    _add_folder_to_zip(archive, arc_root, folder)
                archive.writestr(_MANIFEST_ARCNAME, json.dumps(manifest, indent=2))
    except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        raise BackupError(f"Échec de la création de la sauvegarde : {exc}") from exc

    _remember_last_backup(zip_path)

    # La rétention ne s'applique qu'au dossier géré.
    if destination_dir is None:
        prune_backups()

    return zip_path


# --- Vérification d'intégrité ---------------------------------------------
def verify_backup(zip_path: str | Path) -> bool:
    """Vérifie qu'une sauvegarde est exploitable (ZIP valide + base saine).

    Lève ``BackupError`` avec un message clair en cas de problème.
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise BackupError(f"Fichier introuvable : {zip_path}")

    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            bad = archive.testzip()
            if bad is not None:
                raise BackupError(f"Archive corrompue (fichier : {bad}).")
            if _DB_ARCNAME not in archive.namelist():
                raise BackupError(
                    "La sauvegarde ne contient pas la base de données (gestion.db)."
                )
            with tempfile.TemporaryDirectory() as tmp:
                extracted = Path(tmp) / _DB_ARCNAME
                extracted.write_bytes(archive.read(_DB_ARCNAME))
                connection = sqlite3.connect(str(extracted))
                try:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                finally:
                    connection.close()
                if not result or result[0] != "ok":
                    raise BackupError("La base de données de la sauvegarde est corrompue.")
    except zipfile.BadZipFile as exc:
        raise BackupError("Le fichier n'est pas une archive ZIP valide.") from exc
    return True


# --- Restauration ----------------------------------------------------------
def restore_backup(zip_path: str | Path, safety_backup: bool = True) -> Optional[Path]:
    """Restaure une sauvegarde complète.

    Étapes :
    1. vérifier l'intégrité de l'archive ;
    2. créer une sauvegarde de sécurité de l'état actuel ;
    3. restaurer la base, les logos, les tickets et les exports.

    Retourne le chemin de la sauvegarde de sécurité (ou ``None``).
    """
    zip_path = Path(zip_path)
    verify_backup(zip_path)

    safety_path: Optional[Path] = None
    if safety_backup and config.DATABASE_FILE.exists():
        try:
            safety_path = create_full_backup(manual=False, prefix=_SAFETY_PREFIX)
        except BackupError:
            safety_path = None  # On n'empêche pas la restauration si la sécurité échoue.

    # Libère toute connexion SQLAlchemy ouverte afin que le fichier de base et
    # ses journaux WAL/SHM ne soient plus verrouillés pendant le remplacement.
    try:
        from app.database import connection

        connection.engine.dispose()
    except Exception:
        pass

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            with zipfile.ZipFile(zip_path, "r") as archive:
                archive.extractall(tmp_dir)

            # 1) Base de données.
            extracted_db = tmp_dir / _DB_ARCNAME
            if not extracted_db.exists():
                raise BackupError("Base de données absente de la sauvegarde.")
            config.ensure_directories()
            # Retire d'abord les journaux WAL/SHM courants avant d'écraser la base.
            for suffix in ("-wal", "-shm"):
                stale = Path(str(config.DATABASE_FILE) + suffix)
                if stale.exists():
                    stale.unlink()
            shutil.copy2(extracted_db, config.DATABASE_FILE)
            # Supprime les journaux WAL/SHM devenus incohérents.
            for suffix in ("-wal", "-shm"):
                stale = Path(str(config.DATABASE_FILE) + suffix)
                if stale.exists():
                    stale.unlink()

            # 2) Dossiers de données (logos, tickets, exports).
            for arc_root, folder in _DATA_FOLDERS.items():
                extracted_folder = tmp_dir / arc_root
                if extracted_folder.exists():
                    if folder.exists():
                        shutil.rmtree(folder)
                    shutil.copytree(extracted_folder, folder)
                    folder.mkdir(parents=True, exist_ok=True)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackupError(f"Échec de la restauration : {exc}") from exc

    return safety_path


# --- Listage / rétention ---------------------------------------------------
def list_backups(directory: str | Path | None = None) -> List[Path]:
    """Liste les sauvegardes (ZIP), de la plus récente à la plus ancienne."""
    folder = Path(directory) if directory else config.BACKUP_DIR
    if not folder.exists():
        return []
    files = [p for p in folder.glob("*.zip") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def backup_infos(directory: str | Path | None = None) -> List[BackupInfo]:
    """Retourne les métadonnées des sauvegardes existantes."""
    infos = []
    for path in list_backups(directory):
        stat = path.stat()
        infos.append(
            BackupInfo(
                path=path,
                created_at=datetime.fromtimestamp(stat.st_mtime),
                size_bytes=stat.st_size,
            )
        )
    return infos


def latest_backup() -> Optional[BackupInfo]:
    """Retourne la sauvegarde la plus récente (dossier géré), ou ``None``."""
    infos = backup_infos()
    return infos[0] if infos else None


def get_retention() -> int:
    """Nombre de sauvegardes à conserver (préférence, défaut 10)."""
    from app.services import settings_service

    raw = settings_service.get_setting(SETTING_RETENTION, str(DEFAULT_RETENTION))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_RETENTION
    return max(1, value)


def prune_backups(keep: Optional[int] = None) -> List[Path]:
    """Supprime les sauvegardes les plus anciennes au-delà de la limite.

    Retourne la liste des fichiers supprimés.
    """
    keep = keep if keep is not None else get_retention()
    backups = list_backups()
    removed = []
    for path in backups[keep:]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    return removed


# --- Sauvegarde automatique -----------------------------------------------
def _remember_last_backup(path: Path) -> None:
    try:
        from app.services import settings_service

        settings_service.set_setting(SETTING_LAST_PATH, str(path))
    except Exception:
        pass  # La mémorisation ne doit jamais bloquer une sauvegarde réussie.


def is_auto_enabled() -> bool:
    from app.services import settings_service

    return settings_service.get_setting(SETTING_AUTO_ENABLED, "0") == "1"


def get_frequency() -> str:
    from app.services import settings_service

    freq = settings_service.get_setting(SETTING_AUTO_FREQUENCY, "hebdomadaire")
    return freq if freq in _FREQUENCY_DELTA else "hebdomadaire"


def is_backup_due() -> bool:
    """Indique si une sauvegarde automatique est nécessaire selon la fréquence."""
    last = latest_backup()
    if last is None:
        return True
    return datetime.now() - last.created_at >= _FREQUENCY_DELTA[get_frequency()]


def run_startup_auto_backup() -> Optional[Path]:
    """Au démarrage : crée une sauvegarde automatique si activée et échue."""
    if not is_auto_enabled():
        return None
    if not is_backup_due():
        return None
    return create_full_backup(manual=False)


# --- Compatibilité ascendante ---------------------------------------------
def create_backup(manual: bool = True) -> Path:
    """Alias historique : crée une sauvegarde complète dans le dossier géré."""
    return create_full_backup(manual=manual)


def auto_backup_if_needed(interval_hours: int = 12) -> Optional[Path]:  # noqa: ARG001
    """Alias historique : délègue à la sauvegarde automatique paramétrable."""
    return run_startup_auto_backup()
