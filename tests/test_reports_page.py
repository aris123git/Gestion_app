import os, tempfile, unittest
from unittest.mock import patch
os.environ.setdefault("GESTION_DATA_DIR", tempfile.mkdtemp())
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"


class ReportsPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from app.database.connection import init_database
        from app.database.seed import seed_all
        init_database()
        seed_all()

    def test_cards_status_filter_sort(self):
        from app.controllers.product_controller import ProductController as P
        from app.controllers.sale_controller import CartLine, PaymentLine, SaleController as SC
        from app.ui.pages.reports_page import ReportsPage
        from app.ui.state import AppState
        p = P.create({"name": "Rapport Riz", "sale_price": 1000, "purchase_price": 600, "quantity": 20})
        SC.create_sale([CartLine(p.id, p.name, 1000, 2)], [PaymentLine("Espèces", 2000)], amount_received=2000)
        SC.create_sale([CartLine(p.id, p.name, 1000, 1)], [PaymentLine("Espèces", 1000)], amount_received=1000)
        st = AppState()
        st.can = lambda _p: True
        pg = ReportsPage(st)
        pg._generate()
        self.assertEqual(pg.history_table.columnCount(), 7)
        self.assertGreaterEqual(pg.history_table.rowCount(), 2)
        self.assertEqual(pg.history_table.item(0, 5).text(), "Payée")
        self.assertIn("3", pg.lbl_revenue["text"].text().replace(" ", "").replace(" ", ""))
        pg.status_filter.setCurrentIndex(pg.status_filter.findData("Annulée"))
        self.assertEqual(pg.history_table.rowCount(), 0)
        pg.status_filter.setCurrentIndex(0)
        pg._sort_by(6)
        self.assertGreaterEqual(pg.history_table.rowCount(), 2)
        self.assertTrue(pg.chart.values and max(pg.chart.values) > 0)


if __name__ == "__main__":
    unittest.main()
