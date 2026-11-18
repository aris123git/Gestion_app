import os
import tempfile
import unittest

os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GESTION_DATA_DIR"] = tempfile.mkdtemp()


class SuppliersPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from app.database.connection import init_database
        from app.database.seed import seed_all
        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()

    def test_list_detail_and_due_filter(self):
        from app.controllers.product_controller import ProductController as PC
        from app.controllers.supplier_controller import SupplierController as SC
        from app.services.purchase_service import PurchaseLine, PurchaseService
        from app.ui.pages.suppliers_page import SuppliersPage
        from app.ui.state import AppState

        s1 = SC.create({"name": "Four A", "phone": "+22670000021"}).id
        SC.create({"name": "Four B", "phone": "+22670000022"})
        pid = PC.create({"name": "Art S", "sale_price": 10, "purchase_price": 5, "quantity": 0, "min_stock": 2, "supplier_id": s1}).id
        PurchaseService.create([PurchaseLine(pid, "Art S", 10, 5)], supplier_id=s1, invoice_number="F-9", amount_paid=20)
        st = AppState()
        st.can = lambda _p: True
        page = SuppliersPage(st)
        page.refresh()
        names = [page.table.item(r, 0).text() for r in range(page.table.rowCount())]
        page.table.setCurrentCell(names.index("Four A"), 0)
        self.assertIn("F-9", page.d_buys.text())
        self.assertIn("reste", page.d_buys.text())
        page._set_filter("due")
        names = [page.table.item(r, 0).text() for r in range(page.table.rowCount())]
        self.assertEqual(names, ["Four A"])


if __name__ == "__main__":
    unittest.main()
