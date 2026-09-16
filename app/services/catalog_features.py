"""Options catalogue caisse : images produits + navigation par catégories."""

from __future__ import annotations

from app.services import settings_service

SETTING_PRODUCT_IMAGES = "catalog_product_images"
SETTING_CATEGORY_BROWSER = "catalog_category_browser"


def _default() -> str:
    """En Maquis Caisse, l'affichage tablette (vignettes + puces) est le défaut."""
    from app.services import product_profile

    return "1" if product_profile.is_maquis() else "0"


def product_images_enabled() -> bool:
    return settings_service.get_setting(SETTING_PRODUCT_IMAGES, _default()) == "1"


def set_product_images_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_PRODUCT_IMAGES, "1" if enabled else "0")


def category_browser_enabled() -> bool:
    return settings_service.get_setting(SETTING_CATEGORY_BROWSER, _default()) == "1"


def set_category_browser_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_CATEGORY_BROWSER, "1" if enabled else "0")
