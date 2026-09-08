"""Profil produit NexaGes : Gestion App ou Maquis Caisse.

Sur un nouveau poste, l'utilisateur choisit le produit une fois
(avant l'activation). Le choix est stocké localement et ne se redemande pas.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from app import config

logger = logging.getLogger(__name__)

PRODUCT_GESTION = "gestion_app"
PRODUCT_MAQUIS = "maquis_caisse"

PRODUCT_LABELS = {
    PRODUCT_GESTION: "Gestion App",
    PRODUCT_MAQUIS: "Maquis Caisse",
}

PRODUCT_DESCRIPTIONS = {
    PRODUCT_GESTION: (
        "Commerce, boutique, pharmacie, quincaillerie… "
        "Caisse, stock, achats, dettes, rapports, avoirs clients — "
        "et fidélité bénéfices (produit boutique offert)."
    ),
    PRODUCT_MAQUIS: (
        "Restaurants, maquis, buvettes, bars… "
        "Caisse, tables, commandes ouvertes, stock, avoirs, dettes — "
        "fidélité bénéfices (produit offert) — version PC de Maquis Caisse."
    ),
}

# Fichier machine (comme activation.dat) — indépendant de la boutique.
PROFILE_FILE = config.DATA_DIR / "nexages_product.dat"

# Noms affichés du logiciel parent.
PARENT_NAME = "NexaGes"
PARENT_VENDOR = "NexaDigit"


def _normalize(value: str) -> str:
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


def profile_path() -> Path:
    config.ensure_directories()
    return PROFILE_FILE


def get_product() -> Optional[str]:
    """Retourne le code produit, ou None si pas encore choisi."""
    env = os.environ.get("NEXAGES_PRODUCT", "").strip()
    if env:
        key = _normalize(env)
        if key in ("gestion", "gestion_app", "gestionapp"):
            return PRODUCT_GESTION
        if key in ("maquis", "maquis_caisse", "maquiscaisse"):
            return PRODUCT_MAQUIS
    path = profile_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        code = _normalize(str(data.get("product") or ""))
        if code in PRODUCT_LABELS:
            return code
    except Exception:
        logger.exception("Lecture du profil produit impossible")
    return None


def is_product_chosen() -> bool:
    return get_product() is not None


def set_product(product: str) -> None:
    code = _normalize(product)
    if code in ("gestion", "gestionapp"):
        code = PRODUCT_GESTION
    if code in ("maquis", "maquiscaisse"):
        code = PRODUCT_MAQUIS
    if code not in PRODUCT_LABELS:
        raise ValueError(f"Produit inconnu : {product}")
    path = profile_path()
    path.write_text(
        json.dumps({"product": code, "parent": PARENT_NAME}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        from app.services import settings_service

        settings_service.set_setting("nexages_product", code)
    except Exception:
        logger.debug("Impossible de miroirer le produit dans settings.", exc_info=True)


def require_product() -> str:
    """Produit courant pour l'UI. Ne persiste rien (évite de court-circuiter le choix 1er PC)."""
    return get_product() or PRODUCT_GESTION


def is_gestion() -> bool:
    return require_product() == PRODUCT_GESTION


def is_maquis() -> bool:
    return require_product() == PRODUCT_MAQUIS


def supports_profit_loyalty() -> bool:
    """Fidélité bénéfices (produit offert) : Gestion App et Maquis Caisse."""
    return require_product() in (PRODUCT_GESTION, PRODUCT_MAQUIS)


def product_label(product: Optional[str] = None) -> str:
    code = product or require_product()
    return PRODUCT_LABELS.get(code, PARENT_NAME)


def window_title() -> str:
    return f"{PARENT_NAME} — {product_label()}"


def app_display_name() -> str:
    """Nom court pour barre latérale / login selon le produit."""
    return product_label()
