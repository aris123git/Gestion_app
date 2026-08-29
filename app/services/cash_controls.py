"""Plafonds caisse (remise / crédit) pour limiter les écarts caissier ↔ patron."""

from __future__ import annotations

from typing import Optional, Tuple

from app.services import permissions as perms, settings_service

# Défauts raisonnables (surchargeables via Paramètres).
DEFAULT_MAX_DISCOUNT_PERCENT = 10.0  # % du sous-total
DEFAULT_MAX_CREDIT_AMOUNT = 100_000.0  # devise du commerce
DEFAULT_MAX_FREE_AMOUNT = 50_000.0  # montant libre max par ligne (caissier)
DEFAULT_VARIANCE_NOTE_THRESHOLD = 500.0  # écart caisse → note obligatoire


def get_max_discount_percent() -> float:
    raw = settings_service.get_setting(
        "cashier_max_discount_percent", str(int(DEFAULT_MAX_DISCOUNT_PERCENT))
    )
    try:
        return max(0.0, min(100.0, float(raw)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_DISCOUNT_PERCENT


def get_max_credit_amount() -> float:
    raw = settings_service.get_setting(
        "cashier_max_credit_amount", str(int(DEFAULT_MAX_CREDIT_AMOUNT))
    )
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_MAX_CREDIT_AMOUNT


def get_max_free_amount() -> float:
    raw = settings_service.get_setting(
        "cashier_max_free_amount", str(int(DEFAULT_MAX_FREE_AMOUNT))
    )
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_MAX_FREE_AMOUNT


def get_variance_note_threshold() -> float:
    raw = settings_service.get_setting(
        "cash_variance_note_threshold", str(int(DEFAULT_VARIANCE_NOTE_THRESHOLD))
    )
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_VARIANCE_NOTE_THRESHOLD


def set_limits(
    discount_percent: float,
    credit_amount: float,
    *,
    free_amount: Optional[float] = None,
    variance_threshold: Optional[float] = None,
) -> None:
    settings_service.set_setting(
        "cashier_max_discount_percent", str(round(float(discount_percent), 2))
    )
    settings_service.set_setting(
        "cashier_max_credit_amount", str(round(float(credit_amount), 2))
    )
    if free_amount is not None:
        settings_service.set_setting(
            "cashier_max_free_amount", str(round(float(free_amount), 2))
        )
    if variance_threshold is not None:
        settings_service.set_setting(
            "cash_variance_note_threshold",
            str(round(float(variance_threshold), 2)),
        )


def is_cashier_user(user) -> bool:
    role = getattr(user, "role", None) if user is not None else None
    return role == perms.ROLE_CASHIER


def limits_for_user(user) -> Tuple[Optional[float], Optional[float]]:
    """Retourne (max_discount_percent, max_credit_amount) ou (None, None) si illimité."""
    if not is_cashier_user(user):
        return None, None
    return get_max_discount_percent(), get_max_credit_amount()


def max_discount_amount(subtotal: float, user) -> Optional[float]:
    """Plafond absolu de remise pour ``user``, ou None si illimité."""
    percent, _ = limits_for_user(user)
    if percent is None:
        return None
    return round(max(0.0, float(subtotal)) * percent / 100.0, 2)


def assert_cashier_sale_limits(
    *,
    user,
    subtotal: float,
    discount: float,
    credit_amount: float,
    free_amount_lines: Optional[list] = None,
) -> None:
    """Lève ValueError si le caissier dépasse les plafonds configurés."""
    max_disc = max_discount_amount(subtotal, user)
    _, max_credit = limits_for_user(user)
    if max_disc is not None and float(discount) > max_disc + 0.009:
        raise ValueError(
            f"Remise trop élevée pour un caissier "
            f"(max {max_disc:g}, soit {get_max_discount_percent():g} % du panier)."
        )
    if max_credit is not None and float(credit_amount) > max_credit + 0.009:
        raise ValueError(
            f"Dette trop élevée pour un caissier "
            f"(max {max_credit:g} {settings_service.get_currency()})."
        )
    if is_cashier_user(user) and free_amount_lines:
        ceiling = get_max_free_amount()
        for amount in free_amount_lines:
            if float(amount) > ceiling + 0.009:
                raise ValueError(
                    f"Montant libre trop élevé pour un caissier "
                    f"(max {ceiling:g} {settings_service.get_currency()} par ligne)."
                )


def assert_sale_permissions(
    *,
    user,
    discount: float,
    credit_amount: float,
) -> None:
    """Contrôle côté serveur des permissions remise / crédit."""
    if user is None:
        return
    if float(discount) > 0.009 and not perms.can(user, perms.APPLY_DISCOUNT):
        raise ValueError("Vous n'avez pas l'autorisation d'appliquer une remise.")
    if float(credit_amount) > 0.009 and not perms.can(user, perms.SELL_ON_CREDIT):
        raise ValueError("Vous n'avez pas l'autorisation de vendre à crédit.")
