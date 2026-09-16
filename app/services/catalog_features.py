"""Options catalogue caisse : images produits + navigation par catégories."""

from __future__ import annotations

from app.services import settings_service

SETTING_PRODUCT_IMAGES = "catalog_product_images"
SETTING_CATEGORY_BROWSER = "catalog_category_browser"
SETTING_TOUCH_LAYOUT = "pos_touch_layout"


def product_images_enabled() -> bool:
    return settings_service.get_setting(SETTING_PRODUCT_IMAGES, "0") == "1"


def set_product_images_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_PRODUCT_IMAGES, "1" if enabled else "0")


def category_browser_enabled() -> bool:
    return settings_service.get_setting(SETTING_CATEGORY_BROWSER, "0") == "1"


def set_category_browser_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_CATEGORY_BROWSER, "1" if enabled else "0")


def touch_layout_enabled() -> bool:
    """Caisse en interface tactile (tuiles produits + ardoise à grosses lignes).

    Par défaut : activée pour Maquis Caisse (même saisie qu'à la table),
    désactivée pour Gestion App (caisse clavier / code-barres).
    """
    from app.services import product_profile

    raw = str(settings_service.get_setting(SETTING_TOUCH_LAYOUT, "") or "").strip()
    if raw == "":
        return product_profile.is_maquis()
    return raw not in ("0", "false", "False")


def set_touch_layout_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_TOUCH_LAYOUT, "1" if enabled else "0")
