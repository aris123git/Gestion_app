"""Vérification des mises à jour : compare la version installée à la dernière publication GitHub.

Ne remplace rien automatiquement : l'utilisateur télécharge le nouvel exe et le garde à côté de l'ancien.
Fonctionne seulement si les « Releases » du dépôt sont publiques et si l'ordinateur a internet.
"""

from __future__ import annotations

import json
import re
import urllib.request
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
        notes=str(data.get("body", "") or "")[:1500], asset_url=str(assets[0].get("browser_download_url", "")) if assets else "",
    )
