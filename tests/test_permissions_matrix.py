"""Matrice des droits : un caissier ne doit pas pouvoir faire les actions sensibles."""
import unittest
from types import SimpleNamespace as U

from app.services import permissions as p

SENSITIVE = [p.MANAGE_SETTINGS, p.MANAGE_USERS, p.MANAGE_PRICES, p.DELETE_PRODUCTS, p.MANAGE_PRODUCTS,
             p.CANCEL_SALE, p.CANCEL_SALE_WITH_AUTH, p.CREATE_MANUAL_CLIENT_DEBT, p.VIEW_PROFITS,
             p.VIEW_REPORTS, p.VIEW_AUDIT, p.MANAGE_PURCHASES, p.MANAGE_SUPPLIERS, p.MANAGE_EXPENSES]


class PermissionTests(unittest.TestCase):
    def test_cashier_has_no_sensitive_permission(self):
        for perm in SENSITIVE:
            self.assertFalse(p.can(U(role=p.ROLE_CASHIER), perm), perm)

    def test_cashier_can_apply_discount_and_sell_on_credit(self):
        for perm in (p.APPLY_DISCOUNT, p.SELL, p.SELL_ON_CREDIT):
            self.assertTrue(p.can(U(role=p.ROLE_CASHIER), perm), perm)

    def test_manager_cannot_touch_settings_or_users(self):
        for perm in (p.MANAGE_SETTINGS, p.MANAGE_USERS, p.CANCEL_SALE, p.CREATE_MANUAL_CLIENT_DEBT):
            self.assertFalse(p.can(U(role=p.ROLE_MANAGER), perm), perm)

    def test_manager_cancels_only_with_admin_auth(self):
        self.assertTrue(p.requires_auth_to_cancel(U(role=p.ROLE_MANAGER)))
        self.assertFalse(p.requires_auth_to_cancel(U(role=p.ROLE_ADMIN)))

    def test_unknown_role_and_no_user_have_nothing(self):
        self.assertFalse(p.can(None, p.SELL))
        self.assertFalse(p.can(U(role="Inconnu"), p.SELL))

    def test_admin_has_everything(self):
        for perm in p._ALL_PERMISSIONS:
            self.assertTrue(p.can(U(role=p.ROLE_ADMIN), perm))


if __name__ == "__main__":
    unittest.main()
