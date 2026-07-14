"""Hachage et vérification des mots de passe (PBKDF2, bibliothèque standard).

On évite toute dépendance externe : ``hashlib.pbkdf2_hmac`` fournit un hachage
salé robuste, suffisant pour une application de caisse hors ligne.
"""

from __future__ import annotations

import hashlib
import hmac
import os

_ALGORITHM = "sha256"
_ITERATIONS = 120_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Retourne un hachage salé au format ``pbkdf2$iter$salt$hash``."""
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        _ALGORITHM, password.encode("utf-8"), salt, _ITERATIONS
    )
    return f"pbkdf2${_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Vérifie un mot de passe en clair contre un hachage stocké."""
    try:
        scheme, iterations, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    derived = hashlib.pbkdf2_hmac(
        _ALGORITHM,
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations),
    )
    return hmac.compare_digest(derived.hex(), hash_hex)
