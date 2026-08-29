"""Tests filtres / tri des dettes clients."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_debts_tabs_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.client_controller import ClientController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.debt import STATUS_PAID  # noqa: E402
from app.services.debt_service import DebtService  # noqa: E402


class DebtTabsFilterTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cls.client = ClientController.create(
            {"name": "Client Dettes Tabs", "phone": "770011223"}
        )
        today = date.today()
        DebtService.create_debt(
            cls.client.id, 1000, due_date=today - timedelta(days=5), note="échue"
        )
        DebtService.create_debt(
            cls.client.id, 2000, due_date=today + timedelta(days=10), note="ouverte"
        )
        paid = DebtService.create_debt(
            cls.client.id, 500, due_date=today + timedelta(days=3), note="à solder"
        )
        DebtService.pay_debt(paid.id, 500, payment_method="Espèces")

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_unpaid_excludes_paid(self) -> None:
        unpaid = DebtService.list_debts(
            client_id=self.client.id, filter_mode="unpaid"
        )
        self.assertTrue(all(d.status != STATUS_PAID for d in unpaid))
        self.assertGreaterEqual(len(unpaid), 2)

    def test_paid_only(self) -> None:
        paid = DebtService.list_debts(client_id=self.client.id, filter_mode="paid")
        self.assertTrue(paid)
        self.assertTrue(all(d.status == STATUS_PAID for d in paid))

    def test_overdue_only(self) -> None:
        overdue = DebtService.list_debts(
            client_id=self.client.id, filter_mode="overdue"
        )
        self.assertTrue(overdue)
        self.assertTrue(all(d.is_overdue for d in overdue))

    def test_recent_sort_newest_first(self) -> None:
        debts = DebtService.list_debts(
            client_id=self.client.id, filter_mode="all", sort_by="recent"
        )
        self.assertGreaterEqual(len(debts), 3)
        dates = [d.created_at for d in debts if d.created_at]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_all_contains_each_bucket(self) -> None:
        all_debts = DebtService.list_debts(
            client_id=self.client.id, filter_mode="all"
        )
        unpaid = DebtService.list_debts(
            client_id=self.client.id, filter_mode="unpaid"
        )
        paid = DebtService.list_debts(client_id=self.client.id, filter_mode="paid")
        self.assertGreaterEqual(len(all_debts), len(unpaid) + len(paid))


if __name__ == "__main__":
    unittest.main()
