"""Options catalogue caisse : images produits + navigation par catégories."""

from __future__ import annotations

from app.services import product_profile, settings_service

SETTING_PRODUCT_IMAGES = "catalog_product_images"
SETTING_CATEGORY_BROWSER = "catalog_category_browser"


def product_images_enabled() -> bool:
    # Maquis Caisse PC : grille images comme la tablette (toujours).
    if product_profile.is_maquis():
        return True
    return settings_service.get_setting(SETTING_PRODUCT_IMAGES, "0") == "1"


def set_product_images_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_PRODUCT_IMAGES, "1" if enabled else "0")


def category_browser_enabled() -> bool:
    # Maquis : chips catégories comme navigation tactile tablette.
    if product_profile.is_maquis():
        stored = settings_service.get_setting(SETTING_CATEGORY_BROWSER, "")
        if stored == "":
            return True
        return stored == "1"
    return settings_service.get_setting(SETTING_CATEGORY_BROWSER, "0") == "1"


def set_category_browser_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_CATEGORY_BROWSER, "1" if enabled else "0")
