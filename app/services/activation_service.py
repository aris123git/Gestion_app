"""Activation du logiciel par clé maître (hors ligne, un seul exécutable).

Au premier démarrage, l'application exige un **code d'activation**. Une fois le
bon code saisi, un fichier caché ``activation.dat`` est créé dans le dossier de
données du poste et le code n'est plus jamais redemandé.

- Aucun accès Internet requis.
- Le code maître est intégré à l'application (constante ``MASTER_KEY``), et peut
  être surchargé via la variable d'environnement ``NEXAPOS_ACTIVATION_KEY``.
- Le fichier d'activation stocke uniquement une empreinte (SHA-256) du code, pas
  le code en clair.
- L'activation est liée au poste : ``activation.dat`` contient aussi une
  empreinte de la machine et du dossier de données.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

from app import config

# Code d'activation maître par défaut. Modifiable ici ou via la variable
# d'environnement NEXAPOS_ACTIVATION_KEY.
MASTER_KEY = "ARIS-2026-NEXA-5363"

ACTIVATION_FILE = config.DATA_DIR / "activation.dat"


def _master_key() -> str:
    return os.environ.get("NEXAPOS_ACTIVATION_KEY", MASTER_KEY)


def _normalize(code: str) -> str:
    """Normalise un code (insensible à la casse et aux espaces superflus)."""
    return "".join(str(code).split()).upper()


def _expected_token() -> str:
    return hashlib.sha256(_normalize(_master_key()).encode("utf-8")).hexdigest()


def _machine_id() -> str:
    """Empreinte locale liant l'activation au poste et au dossier de données."""
    raw = f"{socket.gethostname()}|{config.DATA_DIR.resolve()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _set_hidden(path: Path) -> None:
    """Rend le fichier caché sous Windows (sans effet ailleurs)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            FILE_ATTRIBUTE_HIDDEN = 0x02
            ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
        except Exception:
            pass


def is_activated() -> bool:
    """Indique si le logiciel est déjà activé sur ce poste."""
    # Bypass explicite pour les tests automatisés / environnements headless.
    if os.environ.get("NEXAPOS_SKIP_ACTIVATION") == "1":
        return True
    if not ACTIVATION_FILE.exists():
        return False
    try:
        data = json.loads(ACTIVATION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("token") == _expected_token() and data.get("machine_id") == _machine_id()


def verify_code(code: str) -> bool:
    """Vérifie qu'un code correspond à la clé maître (sans rien enregistrer)."""
    return _normalize(code) == _normalize(_master_key())


def activate(code: str) -> bool:
    """Valide le code et, si correct, enregistre l'activation. Retourne le succès."""
    if not verify_code(code):
        return False
    config.ensure_directories()
    payload = {
        "token": _expected_token(),
        "machine_id": _machine_id(),
        "activated_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        ACTIVATION_FILE.write_text(json.dumps(payload), encoding="utf-8")
        _set_hidden(ACTIVATION_FILE)
    except OSError:
        return False
    return True
