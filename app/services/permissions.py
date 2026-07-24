"""Matrice des permissions par rôle (Administrateur / Gestionnaire / Caissier).

Le caissier se limite à la vente et à la consultation utile en caisse.
Le gestionnaire gère stocks, produits, prix et rapports, mais pas les
paramètres critiques ni les comptes utilisateurs.
L'administrateur a le contrôle total.
"""

from __future__ import annotations

from typing import FrozenSet, Optional

# --- Rôles (libellés stockés en base / affichés dans l'UI) -----------------
ROLE_ADMIN = "Administrateur"
ROLE_MANAGER = "Gestionnaire"
ROLE_CASHIER = "Caissier"

# --- Permissions -----------------------------------------------------------
SELL = "sell"
PRINT_TICKET = "print_ticket"
CANCEL_SALE = "cancel_sale"  # sans re-auth (admin)
CANCEL_SALE_WITH_AUTH = "cancel_sale_with_auth"  # gestionnaire + MDP admin
VIEW_PRODUCTS = "view_products"
MANAGE_PRODUCTS = "manage_products"
DELETE_PRODUCTS = "delete_products"
MANAGE_PRICES = "manage_prices"
MANAGE_STOCK = "manage_stock"
MANAGE_CATEGORIES = "manage_categories"
MANAGE_SUPPLIERS = "manage_suppliers"
MANAGE_EXPENSES = "manage_expenses"
MANAGE_CLIENTS = "manage_clients"
VIEW_REPORTS = "view_reports"
VIEW_PROFITS = "view_profits"
VIEW_DASHBOARD = "view_dashboard"
MANAGE_SETTINGS = "manage_settings"
MANAGE_USERS = "manage_users"

_ALL_PERMISSIONS: FrozenSet[str] = frozenset(
    {
        SELL,
        PRINT_TICKET,
        CANCEL_SALE,
        CANCEL_SALE_WITH_AUTH,
        VIEW_PRODUCTS,
        MANAGE_PRODUCTS,
        DELETE_PRODUCTS,
        MANAGE_PRICES,
        MANAGE_STOCK,
        MANAGE_CATEGORIES,
        MANAGE_SUPPLIERS,
        MANAGE_EXPENSES,
        MANAGE_CLIENTS,
        VIEW_REPORTS,
        VIEW_PROFITS,
        VIEW_DASHBOARD,
        MANAGE_SETTINGS,
        MANAGE_USERS,
    }
)

ROLE_PERMISSIONS: dict[str, FrozenSet[str]] = {
    ROLE_ADMIN: _ALL_PERMISSIONS,
    ROLE_MANAGER: frozenset(
        {
            SELL,
            PRINT_TICKET,
            CANCEL_SALE_WITH_AUTH,
            VIEW_PRODUCTS,
            MANAGE_PRODUCTS,
            DELETE_PRODUCTS,
            MANAGE_PRICES,
            MANAGE_STOCK,
            MANAGE_CATEGORIES,
            MANAGE_SUPPLIERS,
            MANAGE_EXPENSES,
            MANAGE_CLIENTS,
            VIEW_REPORTS,
            VIEW_PROFITS,
            VIEW_DASHBOARD,
        }
    ),
    ROLE_CASHIER: frozenset(
        {
            SELL,
            PRINT_TICKET,
            VIEW_PRODUCTS,
            MANAGE_CLIENTS,
            VIEW_REPORTS,
            VIEW_DASHBOARD,
        }
    ),
}


def permissions_for(role: Optional[str]) -> FrozenSet[str]:
    """Retourne l'ensemble des permissions d'un rôle (vide si inconnu)."""
    if not role:
        return frozenset()
    return ROLE_PERMISSIONS.get(role, frozenset())


def can(user, permission: str) -> bool:
    """Indique si ``user`` possède la permission demandée."""
    if user is None:
        return False
    role = getattr(user, "role", None)
    return permission in permissions_for(role)


def can_cancel_sale(user) -> bool:
    """Admin (direct) ou gestionnaire (avec autorisation ultérieure)."""
    return can(user, CANCEL_SALE) or can(user, CANCEL_SALE_WITH_AUTH)


def requires_auth_to_cancel(user) -> bool:
    """True si l'annulation exige le mot de passe d'un administrateur."""
    return not can(user, CANCEL_SALE) and can(user, CANCEL_SALE_WITH_AUTH)
