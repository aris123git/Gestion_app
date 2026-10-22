"""Tests : comptabilité simplifiée (journal, résultat, TVA, trésorerie)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_accounting_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine, SaleController  # noqa: E402
from app.database.connection import engine, init_database, session_scope  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.expense import Expense  # noqa: E402
from app.services import accounting_service as acc  # noqa: E402


class AccountingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cls.p = ProductController.create({"name": "Riz", "sale_price": 1180, "purchase_price": 600, "quantity": 50, "tax_rate": 18})
        SaleController.create_sale([CartLine(cls.p.id, "Riz", 1180, 10)], [PaymentLine("Espèces", 11800)], amount_received=11800)
        with session_scope() as s:
            s.add(Expense(category="Loyer", label="Loyer", amount=2000, date=datetime.now(), notes=""))
        acc.add_manual_entry(date.today(), "Capital", "571", "101", 100000)
        acc.add_manual_entry(date.today(), "Stock initial", "311", "101", 50000)
        cls.data = acc.build(date.today() - timedelta(days=1), date.today())

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_entries_balanced_and_result(self) -> None:
        self.assertEqual(self.data["unbalanced"], [])
        r = self.data["income"]
        self.assertAlmostEqual(r["sales"], 10000)
        self.assertAlmostEqual(r["purchases"], 6000)
        self.assertAlmostEqual(r["margin"], 4000)
        self.assertAlmostEqual(r["result"], 2000)

    def test_balance_sheet_balances(self) -> None:
        s = self.data["sheet"]
        self.assertAlmostEqual(s["total_assets"], s["total_liabilities"])
        # caisse 109 800 + stock (50 000 − 6 000) = 153 800
        self.assertAlmostEqual(s["total_assets"], 153800)

    def test_vat_and_cash(self) -> None:
        self.assertAlmostEqual(self.data["vat"]["collected"], 1800)
        self.assertAlmostEqual(self.data["cash"]["total"], 100000 + 11800 - 2000)

    def test_suggested_opening_stock(self) -> None:
        amount, first = acc.suggested_opening_stock()
        self.assertGreaterEqual(amount, 0)
        self.assertLessEqual(first, date.today())

    def test_manual_entry_validation(self) -> None:
        with self.assertRaises(ValueError):
            acc.add_manual_entry(date.today(), "x", "571", "571", 10)
        with self.assertRaises(ValueError):
            acc.add_manual_entry(date.today(), "x", "571", "101", 0)
        with self.assertRaises(ValueError):
            acc.add_manual_entry(date.today(), "x", "999", "101", 10)

    def test_exports_and_page(self) -> None:
        from app.reports.accounting_export import export_accounting_excel, export_accounting_pdf

        self.assertTrue(export_accounting_excel(self.data, config.EXPORT_DIR / "c.xlsx").exists())
        self.assertGreater(export_accounting_pdf(self.data, config.EXPORT_DIR / "c.pdf").stat().st_size, 1000)
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        from app.ui.pages.accounting_page import AccountingPage
        from app.ui.state import AppState

        page = AccountingPage(AppState())
        page._generate()
        self.assertGreater(page.result_table.rowCount(), 5)
        self.assertGreater(page.balance_table.rowCount(), 3)


if __name__ == "__main__":
    unittest.main()
