"""Point d'entrée de l'application Gestion Commerciale.

Usage :
    python -m app.main
"""

from __future__ import annotations

import sys


def main() -> int:
    from app.ui.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
