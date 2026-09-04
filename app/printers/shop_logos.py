"""Logos par défaut selon le type de commerce (ticket thermique).

Chaque boutique peut :
- utiliser son logo personnalisé (Commerce → Logo) ;
- ou le logo du type (poissonnerie, quincaillerie, etc.).

Le logo n'est jamais un élément fixe du template : il reste optionnel.

Les pictogrammes livrés dans ``app/assets/shop_logos/`` sont composés à partir
d'icônes Lucide (ISC) : badge circulaire monochrome, traits renforcés pour
lisibilité ESC/POS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app import config

# Fichiers dans app/assets/shop_logos/ (sans extension).
_TYPE_TO_SLUG: dict[str, str] = {
    "Boutique": "boutique",
    "Poissonnerie": "poissonnerie",
    "Pharmacie": "pharmacie",
    "Quincaillerie": "quincaillerie",
    "Boucherie": "boucherie",
    "Boulangerie": "boulangerie",
    "Supérette": "superette",
    "Magasin d'électronique": "electronique",
    "Autre commerce": "autre",
}

LOGOS_DIR = config.ASSETS_DIR / "shop_logos"


def shop_type_slug(shop_type: str) -> str:
    return _TYPE_TO_SLUG.get((shop_type or "").strip(), "autre")


def default_logo_path(shop_type: str) -> Optional[Path]:
    """Chemin du logo PNG fourni pour ce type (ou None si absent)."""
    path = LOGOS_DIR / f"{shop_type_slug(shop_type)}.png"
    return path if path.is_file() else None


def list_default_logos() -> list[tuple[str, Path]]:
    """Liste (libellé type, chemin) des logos livrés."""
    out: list[tuple[str, Path]] = []
    for label, slug in _TYPE_TO_SLUG.items():
        path = LOGOS_DIR / f"{slug}.png"
        if path.is_file():
            out.append((label, path))
    return out


def resolve_logo_path(
    *,
    logo_path: str = "",
    shop_type: str = "",
    prefer_default: bool = False,
) -> str:
    """Retourne le chemin logo à imprimer.

    - Si ``prefer_default`` : logo du type (s'il existe).
    - Sinon logo personnalisé s'il existe sur disque.
    - Sinon repli sur le logo du type.
    - Chaîne vide si rien n'est disponible.
    """
    custom = (logo_path or "").strip()
    default = default_logo_path(shop_type)

    if prefer_default and default is not None:
        return str(default)

    if custom:
        p = Path(custom)
        if p.is_file():
            return str(p)

    if default is not None:
        return str(default)
    return ""
