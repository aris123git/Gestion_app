"""Navigation du produit Chantier Pro (BTP, soudure, menuiserie…)."""

from __future__ import annotations

from typing import List, Tuple, Type

from app.i18n import t
from app.services import permissions as perms
from app.services import product_profile

NavEntry = Tuple[str, str, Type, str]


SETTING_SALES = "chantiers_sales_enabled"


def sales_enabled() -> bool:
    from app.services import settings_service

    return product_profile.is_chantiers() and settings_service.get_setting(SETTING_SALES, "0") == "1"


def set_sales_enabled(enabled: bool) -> None:
    from app.services import settings_service

    settings_service.set_setting(SETTING_SALES, "1" if enabled else "0")


SETTING_RENTALS = "chantiers_rentals_enabled"


def rentals_enabled() -> bool:
    from app.services import settings_service

    return product_profile.is_chantiers() and settings_service.get_setting(SETTING_RENTALS, "0") == "1"


def set_rentals_enabled(enabled: bool) -> None:
    from app.services import settings_service

    settings_service.set_setting(SETTING_RENTALS, "1" if enabled else "0")


def build_chantiers_nav_items() -> List[NavEntry]:
    from app.ui.pages.audit_page import AuditPage
    from app.ui.pages.chantiers_dashboard_page import ChantiersDashboardPage
    from app.ui.pages.chantiers_page import ChantiersPage
    from app.ui.pages.clients_page import ClientsPage
    from app.ui.pages.expenses_page import ExpensesPage
    from app.ui.pages.labor_page import LaborPage
    from app.ui.pages.rentals_page import RentalsPage
    from app.ui.pages.settings_page import SettingsPage
    from app.ui.pages.suppliers_page import SuppliersPage
    from app.ui.pages.subcontractors_page import SubcontractorsPage
    from app.ui.pages.users_page import UsersPage

    if not product_profile.is_chantiers():
        return []
    sales = []
    if sales_enabled():
        from app.ui.pages.categories_page import CategoriesPage
        from app.ui.pages.debts_page import DebtsPage
        from app.ui.pages.pos_page import POSPage
        from app.ui.pages.products_page import ProductsPage
        from app.ui.pages.purchases_page import PurchasesPage
        from app.ui.pages.stock_page import StockPage

        sales = [
            (t("nav.pos"), "🛒", POSPage, perms.SELL),
            (t("nav.products"), "📦", ProductsPage, perms.VIEW_PRODUCTS),
            (t("nav.categories"), "🏷️", CategoriesPage, perms.MANAGE_CATEGORIES),
            (t("nav.stock"), "📥", StockPage, perms.MANAGE_STOCK),
            (t("nav.purchases"), "🧾", PurchasesPage, perms.MANAGE_PURCHASES),
            (t("nav.debts"), "💳", DebtsPage, perms.MANAGE_CLIENT_DEBTS),
        ]
    return [
        (t("Tableau de bord"), "📊", ChantiersDashboardPage, perms.ADD_CHANTIER_EXPENSES),
        *sales,
        (t("Chantiers"), "🏗️", ChantiersPage, perms.ADD_CHANTIER_EXPENSES),
        (t("Main-d'œuvre"), "👷", LaborPage, perms.MANAGE_LABOR),
        (t("Sous-traitants"), "🤝", SubcontractorsPage, perms.MANAGE_SUBCONTRACTORS),
        *([(t("Locations"), "🚜", RentalsPage, perms.MANAGE_RENTALS)] if rentals_enabled() else []),
        (t("nav.clients"), "👥", ClientsPage, perms.MANAGE_CLIENTS),
        (t("nav.suppliers"), "🚚", SuppliersPage, perms.MANAGE_SUPPLIERS),
        (t("Charges générales"), "💸", ExpensesPage, perms.MANAGE_EXPENSES),
        (t("nav.audit"), "📝", AuditPage, perms.VIEW_AUDIT),
        (t("nav.users"), "🔐", UsersPage, perms.MANAGE_USERS),
        (t("nav.settings"), "⚙️", SettingsPage, perms.MANAGE_SETTINGS),
    ]
