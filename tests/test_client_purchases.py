"""Tests : recherche des ventes par client et historique des achats d'un client."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import date

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_clientpurch_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.controllers.client_controller import ClientController  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine, SaleController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402


class ClientPurchasesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()
        cls.p = ProductController.create({"name": "Savon", "sale_price": 500, "purchase_price": 300, "quantity": 100}).id
        cls.awa = ClientController.create({"name": "Awa Konaté", "phone": "76111111"}).id
        cls.paul = ClientController.create({"name": "Paul Zongo", "phone": "70222222"}).id
        for cid, qty in ((cls.awa, 1), (cls.awa, 2), (cls.paul, 3)):
            SaleController.create_sale([CartLine(cls.p, "Savon", 500, qty)], [PaymentLine("Espèces", 500 * qty)], amount_received=500 * qty, client_id=cid)
        SaleController.create_sale([CartLine(cls.p, "Savon", 500, 1)], [PaymentLine("Espèces", 500)], amount_received=500)

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_filter_by_client_id(self) -> None:
        self.assertEqual(len(SaleController.list(client_id=self.awa)), 2)
        self.assertEqual(len(SaleController.list(client_id=self.paul)), 1)

    def test_search_by_name_and_phone(self) -> None:
        self.assertEqual(len(SaleController.list(search="konat")), 2)
        self.assertEqual(len(SaleController.list(search="7022")), 1)
        self.assertEqual(len(SaleController.list(search="zzz")), 0)

    def test_search_by_ticket_still_works(self) -> None:
        ticket = SaleController.list(client_id=self.paul)[0].ticket_number
        self.assertEqual(len(SaleController.list(search=ticket)), 1)

    def test_dialog_lists_client_sales_and_filters(self) -> None:
        from app.ui.dialogs.client_purchases_dialog import ClientPurchasesDialog

        dialog = ClientPurchasesDialog(self.awa, "Awa Konaté")
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertIn("2 achat", dialog.summary.text())
        dialog.search.setText("zzz")
        dialog._load()
        self.assertEqual(dialog.table.rowCount(), 0)

    def test_reports_history_has_client_column(self) -> None:
        from app.ui.pages.reports_page import ReportsPage
        from app.ui.state import AppState

        page = ReportsPage(AppState())
        page._generate()
        self.assertEqual(page.history_table.columnCount(), 6)
        names = {page.history_table.item(r, 2).text() for r in range(page.history_table.rowCount())}
        self.assertIn("Awa Konaté", names)
        page.history_search.setText("Paul")
        page._load_history()
        self.assertEqual(page.history_table.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
