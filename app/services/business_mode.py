"""Mode « Entreprise » : active les fonctions propres aux sociétés (bons d'enlèvement et de livraison…).

Une boutique n'en a pas besoin : ces fonctions n'apparaissent que si le type de commerce
(Paramètres → Commerce) est « Entreprise ».
"""

from __future__ import annotations

ENTERPRISE_TYPE = "Entreprise"


def is_enterprise_type(shop_type: str | None) -> bool:
    return (shop_type or "").strip().casefold() == ENTERPRISE_TYPE.casefold()


def is_enterprise() -> bool:
    try:
        from app.services import settings_service

        return is_enterprise_type(settings_service.get_shop_info().shop_type)
    except Exception:
        return False
