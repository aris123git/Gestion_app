"""Options catalogue caisse : images produits + navigation par catégories."""

from __future__ import annotations

from app.services import product_profile, settings_service

SETTING_PRODUCT_IMAGES = "catalog_product_images"
SETTING_CATEGORY_BROWSER = "catalog_category_browser"


def _default_flag(setting_key: str, gestion_default: str) -> str:
    """Maquis Caisse : défaut type tablette (grille + chips) si non configuré."""
    raw = settings_service.get_setting(setting_key, "")
    if raw != "":
        return raw
    if product_profile.is_maquis():
        return "1"
    return gestion_default


def ensure_maquis_tablet_defaults() -> None:
    """Alias historique — préférences Maquis version PC."""
    ensure_maquis_pc_defaults()


def ensure_maquis_pc_defaults() -> None:
    """Premier lancement Maquis : affichage caisse et options PC."""
    if not product_profile.is_maquis():
        return
    if settings_service.get_setting(SETTING_PRODUCT_IMAGES, "") == "":
        set_product_images_enabled(True)
    if settings_service.get_setting(SETTING_CATEGORY_BROWSER, "") == "":
        set_category_browser_enabled(True)
    if settings_service.get_setting("pos_catalog_large_text", "") == "":
        settings_service.set_setting("pos_catalog_large_text", "1")
    from app.services.maquis_settings import ensure_maquis_pc_defaults as _maquis

    _maquis()


def product_images_enabled() -> bool:
    return _default_flag(SETTING_PRODUCT_IMAGES, "0") == "1"


def set_product_images_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_PRODUCT_IMAGES, "1" if enabled else "0")


def category_browser_enabled() -> bool:
    return _default_flag(SETTING_CATEGORY_BROWSER, "0") == "1"


def set_category_browser_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_CATEGORY_BROWSER, "1" if enabled else "0")
