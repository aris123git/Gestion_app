"""Tests : dette manuelle (admin) et paiement ouvert à tous les rôles dettes."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_manual_debt_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.client_controller import ClientController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import permissions as perms  # noqa: E402
from app.services.debt_service import DebtService  # noqa: E402


class ManualDebtPermissionsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cls.client = ClientController.create(
            {"name": "Client Dette Manuelle", "phone": "770099887"}
        )

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_create_manual_debt_admin_only(self) -> None:
        admin = perms.permissions_for(perms.ROLE_ADMIN)
        manager = perms.permissions_for(perms.ROLE_MANAGER)
        cashier = perms.permissions_for(perms.ROLE_CASHIER)
        self.assertIn(perms.CREATE_MANUAL_CLIENT_DEBT, admin)
        self.assertNotIn(perms.CREATE_MANUAL_CLIENT_DEBT, manager)
        self.assertNotIn(perms.CREATE_MANUAL_CLIENT_DEBT, cashier)

    def test_pay_debt_allowed_for_all_roles(self) -> None:
        for role in (perms.ROLE_ADMIN, perms.ROLE_MANAGER, perms.ROLE_CASHIER):
            self.assertIn(
                perms.MANAGE_CLIENT_DEBTS,
                perms.permissions_for(role),
                msg=f"{role} doit pouvoir régler (Payé)",
            )

    def test_add_debt_without_sale(self) -> None:
        before = DebtService.client_summary(self.client.id)["total_remaining"]
        ClientController.add_debt(
            self.client.id,
            3500,
            note="Dette manuelle (hors caisse)",
            username="admin",
        )
        after = DebtService.client_summary(self.client.id)["total_remaining"]
        self.assertAlmostEqual(after, before + 3500, places=2)
        debts = DebtService.list_debts(
            client_id=self.client.id, filter_mode="unpaid", sort_by="recent"
        )
        self.assertTrue(debts)
        self.assertIsNone(debts[0].sale_id)
        self.assertIn("hors caisse", (debts[0].note or "").lower())

    def test_cashier_can_pay_manual_debt(self) -> None:
        debt = DebtService.create_debt(
            self.client.id, 1000, note="à payer par caissier"
        )
        assert debt is not None
        payment = DebtService.pay_debt(
            debt.id, 1000, payment_method="Espèces", username="caissier"
        )
        self.assertAlmostEqual(float(payment.amount), 1000.0, places=2)
        refreshed = DebtService.get(debt.id)
        self.assertIsNotNone(refreshed)
        self.assertAlmostEqual(float(refreshed.amount_remaining), 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
