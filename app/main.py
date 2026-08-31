"""Point d'entrée de l'application Gestion Commerciale.

Usage :
    python -m app.main
"""

from __future__ import annotations

import sys


def main() -> int:
    # Hook d'erreur le plus tôt possible pour les crashes silencieux de l'EXE
    # ``console=False`` → ``%APPDATA%/GestionCommerciale/startup_error.log``.
    from app.startup_log import install_startup_excepthook, write_startup_error

    install_startup_excepthook()

    try:
        from app.ui.app import run

        return run()
    except Exception as exc:
        write_startup_error(exc, note="Échec fatal dans app.main.")
        raise


if __name__ == "__main__":
    sys.exit(main())
