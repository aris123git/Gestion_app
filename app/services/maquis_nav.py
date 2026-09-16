"""Navigation Maquis Caisse PC — alignée sur l'app tablette (MaquisSideBar)."""

from __future__ import annotations

from typing import List, Tuple, Type

from app.i18n import t
from app.services import permissions as perms
from app.services import product_profile

NavEntry = Tuple[str, str, Type, str]


def build_maquis_nav_items() -> List[NavEntry]:
    from app.ui.pages.assistant_page import AssistantPage
    from app.ui.pages.avoirs_page import AvoirsPage
    from app.ui.pages.caisse_session_page import CaisseSessionPage
    from app.ui.pages.categories_page import CategoriesPage
    from app.ui.pages.dashboard_page import DashboardPage
    from app.ui.pages.debts_page import DebtsPage
    from app.ui.pages.order_history_page import OrderHistoryPage
    from app.ui.pages.orders_page import OrdersPage
    from app.ui.pages.pos_page import POSPage
    from app.ui.pages.products_page import ProductsPage
    from app.ui.pages.reports_page import ReportsPage
    from app.ui.pages.settings_page import SettingsPage
    from app.ui.pages.stock_movements_page import StockMovementsPage
    from app.ui.pages.stock_page import StockPage
    from app.ui.pages.tables_page import TablesPage
    from app.ui.pages.users_page import UsersPage

    if not product_profile.is_maquis():
        return []

    return [
        (t("Caisse"), "🛒", POSPage, perms.SELL),
        (t("Commandes"), "🍽️", OrdersPage, perms.SELL),
        (t("Historique"), "📋", OrderHistoryPage, perms.SELL),
        (t("nav.assistant"), "💡", AssistantPage, perms.VIEW_ASSISTANT),
        (t("nav.dashboard"), "📊", DashboardPage, perms.VIEW_DASHBOARD),
        (t("nav.products"), "📦", ProductsPage, perms.VIEW_PRODUCTS),
        (t("nav.categories"), "🏷️", CategoriesPage, perms.MANAGE_CATEGORIES),
        (t("nav.tables"), "🪑", TablesPage, perms.MANAGE_SETTINGS),
        (t("nav.stock"), "📥", StockPage, perms.MANAGE_STOCK),
        (t("Inventaire"), "📒", StockPage, perms.MANAGE_STOCK),
        (t("Relève"), "💵", CaisseSessionPage, perms.VIEW_REPORTS),
        (t("nav.debts"), "💳", DebtsPage, perms.MANAGE_CLIENT_DEBTS),
        (t("nav.credits"), "🎟️", AvoirsPage, perms.MANAGE_CLIENT_DEBTS),
        (t("Mouvements"), "↔️", StockMovementsPage, perms.MANAGE_STOCK),
        (t("nav.reports"), "📈", ReportsPage, perms.VIEW_REPORTS),
        (t("nav.users"), "🔐", UsersPage, perms.MANAGE_USERS),
        (t("nav.settings"), "⚙️", SettingsPage, perms.MANAGE_SETTINGS),
    ]


def maquis_nav_visible(state, entry: NavEntry) -> bool:
    label, _icon, _cls, permission = entry
    if not state.can(permission):
        return False
    admin_only = {
        t("nav.products"),
        t("nav.categories"),
        t("nav.tables"),
        t("nav.users"),
    }
    if label in admin_only and getattr(state.current_user, "role", "") != perms.ROLE_ADMIN:
        return False
    return True
