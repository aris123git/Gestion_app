"""Navigation du produit Chantier Pro (BTP, soudure, menuiserie…)."""

from __future__ import annotations

from typing import List, Tuple, Type

from app.i18n import t
from app.services import permissions as perms
from app.services import product_profile

NavEntry = Tuple[str, str, Type, str]


def build_chantiers_nav_items() -> List[NavEntry]:
    from app.ui.pages.audit_page import AuditPage
    from app.ui.pages.chantiers_page import ChantiersPage
    from app.ui.pages.clients_page import ClientsPage
    from app.ui.pages.expenses_page import ExpensesPage
    from app.ui.pages.settings_page import SettingsPage
    from app.ui.pages.suppliers_page import SuppliersPage
    from app.ui.pages.users_page import UsersPage

    if not product_profile.is_chantiers():
        return []
    return [
        (t("Chantiers"), "🏗️", ChantiersPage, perms.ADD_CHANTIER_EXPENSES),
        (t("nav.clients"), "👥", ClientsPage, perms.MANAGE_CLIENTS),
        (t("nav.suppliers"), "🚚", SuppliersPage, perms.MANAGE_SUPPLIERS),
        (t("Charges générales"), "💸", ExpensesPage, perms.MANAGE_EXPENSES),
        (t("nav.audit"), "📝", AuditPage, perms.VIEW_AUDIT),
        (t("nav.users"), "🔐", UsersPage, perms.MANAGE_USERS),
        (t("nav.settings"), "⚙️", SettingsPage, perms.MANAGE_SETTINGS),
    ]
