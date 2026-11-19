"""Connexion rapide locale à cet ordinateur (pas dans la base partagée).

Un code court, propre à cette installation, permet de déverrouiller un
compte déjà existant sans retaper identifiant + mot de passe à chaque
démarrage. Ce n'est pas un compte séparé : il faut s'être connecté une
première fois avec le vrai mot de passe pour l'activer, le fichier ne
quitte jamais cet ordinateur, et il peut être désactivé à tout moment.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from app import config
from app.utils.security import hash_password, verify_password

_MIN_CODE_LENGTH = 4
_MAX_FAILURES = 5
_BLOCK_SECONDS = 60
_login_failures = 0
_blocked_until = 0.0


def _path() -> Path:
    return config.DATA_DIR / "device_login.json"


def validate_code(code: str) -> None:
    if len(code or "") < _MIN_CODE_LENGTH:
        raise ValueError(f"Le code doit contenir au moins {_MIN_CODE_LENGTH} caractères.")


def get_device_login() -> Optional[dict]:
    """Retourne {user_id, username} si une connexion rapide est configurée ici."""
    p = _path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {"user_id": data["user_id"], "username": data["username"]}
    except Exception:
        return None


def set_device_login(user_id: int, username: str, code: str) -> None:
    validate_code(code)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps({"user_id": user_id, "username": username, "code_hash": hash_password(code)}), encoding="utf-8")


def clear_device_login() -> None:
    p = _path()
    if p.exists():
        p.unlink()


def seconds_blocked() -> int:
    remaining = _blocked_until - time.monotonic()
    return max(0, int(remaining))


def verify_code(code: str) -> bool:
    """Vérifie le code rapide. Bloque temporairement après plusieurs échecs."""
    global _login_failures, _blocked_until
    if seconds_blocked():
        return False
    p = _path()
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ok = verify_password(code, data["code_hash"])
    except Exception:
        ok = False
    if ok:
        _login_failures = 0
        _blocked_until = 0.0
    else:
        _login_failures += 1
        if _login_failures >= _MAX_FAILURES:
            _blocked_until = time.monotonic() + _BLOCK_SECONDS
            _login_failures = 0
    return ok
