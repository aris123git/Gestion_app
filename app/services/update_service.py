"""Vérification des mises à jour : compare la version installée à la dernière publication GitHub.

Mise à jour en un clic : télécharge l'installateur (ou le nouvel exe portable), le lance en silence, ferme le
logiciel puis le relance. Les données (%APPDATA%) ne sont jamais touchées.
Fonctionne seulement si les « Releases » du dépôt sont publiques et si l'ordinateur a internet.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Optional

from app import __version__
from app.services import settings_service

DEFAULT_REPO = "aris123git/Gestion_app"


@dataclass
class UpdateInfo:
    current: str
    latest: str
    url: str
    notes: str
    asset_url: str = ""

    @property
    def is_newer(self) -> bool:
        return version_tuple(self.latest) > version_tuple(self.current)


def version_tuple(value: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", str(value or ""))[:4]) or (0,)


def _fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "NexaGes"})
    with urllib.request.urlopen(request, timeout=6) as response:  # noqa: S310 — URL https fixe vers api.github.com
        return json.loads(response.read().decode("utf-8"))


def check_for_update(fetch: Optional[Callable[[str], dict]] = None) -> UpdateInfo:
    """Lève ``RuntimeError`` (message lisible) si la vérification est impossible."""
    repo = settings_service.get_setting("update_repo", DEFAULT_REPO).strip() or DEFAULT_REPO
    try:
        data = (fetch or _fetch)(f"https://api.github.com/repos/{repo}/releases/latest")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Impossible de vérifier les mises à jour (pas de connexion internet, ou aucune version publiée).") from exc
    assets = [a for a in data.get("assets", []) if str(a.get("name", "")).lower().endswith(".exe")]
    return UpdateInfo(
        current=__version__, latest=str(data.get("tag_name", "") or data.get("name", "")).lstrip("vV"), url=str(data.get("html_url", "")),
        notes=str(data.get("body", "") or "")[:1500], asset_url=str(next((a for a in assets if "setup" in str(a.get("name", "")).lower()), assets[0]).get("browser_download_url", "")) if assets else "",
    )


MIN_SIZE = 1_000_000          # un exe de moins de 1 Mo n'est pas le logiciel : téléchargement incomplet ou page d'erreur


def download(url: str, progress: Optional[Callable[[int, int], bool]] = None, directory: Path | None = None) -> Path:
    """Télécharge ``url`` dans un dossier temporaire. ``progress(lu, total)`` peut renvoyer False pour annuler."""
    if not url.lower().startswith("https://"):
        raise RuntimeError("Adresse de téléchargement non sécurisée.")
    folder = Path(directory) if directory else Path(tempfile.mkdtemp(prefix="gestion_update_"))
    target = folder / (url.rsplit("/", 1)[-1] or "update.exe")
    request = urllib.request.Request(url, headers={"User-Agent": "NexaGes"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, open(target, "wb") as out:  # noqa: S310 — https vérifié
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress and progress(done, total) is False:
                    raise RuntimeError("Téléchargement annulé.")
    except RuntimeError:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        raise RuntimeError("Le téléchargement a échoué (connexion interrompue ?). Réessayez.") from exc
    if target.stat().st_size < MIN_SIZE:
        target.unlink(missing_ok=True)
        raise RuntimeError("Le fichier téléchargé est incomplet. Réessayez.")
    return target


def is_installer(path: Path) -> bool:
    return "setup" in Path(path).name.lower()


def update_command(downloaded: Path, current_exe: Path, pid: int | None = None) -> list[str]:
    """Commande Windows à lancer (détachée) pour appliquer la mise à jour, puis relancer le logiciel."""
    downloaded, current_exe = Path(downloaded), Path(current_exe)
    if is_installer(downloaded):
        # Installateur Inno Setup : silencieux, ferme et relance le logiciel (voir [Run] dans installer/*.iss)
        return [str(downloaded), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
    # Exe portable : un petit script attend la fermeture, remplace l'exe puis le relance
    script = downloaded.with_suffix(".update.cmd")
    script.write_text(
        "@echo off\r\n"
        f":wait\r\ntasklist /FI \"PID eq {pid or 0}\" 2>NUL | find \"{pid or 0}\" >NUL\r\n"
        "if not errorlevel 1 (timeout /t 1 /nobreak >NUL & goto wait)\r\n"
        f"move /Y \"{downloaded}\" \"{current_exe}\" >NUL\r\n"
        f"start \"\" \"{current_exe}\"\r\n"
        "del \"%~f0\"\r\n",
        encoding="utf-8",
    )
    return ["cmd", "/c", str(script)]


def can_self_update() -> bool:
    """Seulement pour l'exe Windows installé (pas en développement)."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def apply_update(downloaded: Path) -> None:
    """Lance la mise à jour en arrière-plan ; l'appelant doit ensuite fermer le logiciel."""
    command = update_command(downloaded, Path(sys.executable), os.getpid())
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(command, close_fds=True, creationflags=flags)  # noqa: S603 — fichier téléchargé depuis les Releases du dépôt
