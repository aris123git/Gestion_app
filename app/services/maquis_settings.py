"""Réglages Maquis Caisse PC (équivalents fonctionnels de l'app mobile, version bureau)."""

from __future__ import annotations

from app.services import product_profile, settings_service

SETTING_TABLES_ENABLED = "tables_enabled"
_LEGACY_TABLES = "maquis_tables_enabled"
SETTING_KITCHEN_AFTER_SAVE = "maquis_kitchen_prompt_after_save"


def tables_enabled() -> bool:
    if not product_profile.is_maquis():
        return False
    raw = settings_service.get_setting(SETTING_TABLES_ENABLED, "")
    if raw == "":
        raw = settings_service.get_setting(_LEGACY_TABLES, "1")
    return raw == "1"


def set_tables_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_TABLES_ENABLED, "1" if enabled else "0")


def kitchen_prompt_after_save() -> bool:
    if not product_profile.is_maquis():
        return False
    return settings_service.get_setting(SETTING_KITCHEN_AFTER_SAVE, "1") == "1"


def set_kitchen_prompt_after_save(enabled: bool) -> None:
    settings_service.set_setting(SETTING_KITCHEN_AFTER_SAVE, "1" if enabled else "0")


def ensure_maquis_pc_defaults() -> None:
    """Premier lancement Maquis : valeurs par défaut version PC."""
    if not product_profile.is_maquis():
        return
    if settings_service.get_setting(SETTING_TABLES_ENABLED, "") == "":
        set_tables_enabled(True)
    if settings_service.get_setting(SETTING_KITCHEN_AFTER_SAVE, "") == "":
        set_kitchen_prompt_after_save(True)
