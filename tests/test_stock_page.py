"""Page Stock : liste des produits + action choisie, champs utiles seulement."""
import os, tempfile, unittest

os.environ["GESTION_DATA_DIR"] = tempfile.mkdtemp()
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class StockPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from app.database.connection import init_database
        from app.database.seed import seed_all

        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()

    def test_actions_update_stock_and_fields(self):
        from unittest import mock
        from app.controllers.product_controller import ProductController as PC
        from app.ui.pages import stock_page
        from app.ui.state import AppState

        pid = PC.create({"name": "Riz test", "sale_price": 1000, "purchase_price": 800, "quantity": 4, "min_stock": 6}).id
        st = AppState()
        st.can = lambda _p: True
        page = stock_page.StockPage(st)
        page.show()
        page.refresh()
        page.product_search.setText("Riz test")
        self.assertEqual(page._current_product_id(), pid)
        with mock.patch.object(stock_page, "info"), mock.patch.object(stock_page, "warn") as warn:
            page._set_action("in")
            self.assertTrue(page.supplier_combo.isVisibleTo(page))
            page.quantity.setValue(20)
            self.assertIn("24", page.preview.text())
            page._save()
            self.assertEqual(float(PC.get(pid).quantity), 24)
            page._set_action("loss")
            self.assertFalse(page.supplier_combo.isVisibleTo(page))
            self.assertTrue(page.loss_reason.isVisibleTo(page))
            page.quantity.setValue(2)
            page._save()
            self.assertEqual(float(PC.get(pid).quantity), 22)
            page._set_action("inv")
            page.quantity.setValue(30)
            page._save()
            self.assertEqual(float(PC.get(pid).quantity), 30)
            page._set_action("fix")
            page.quantity.setValue(31)
            page._save()              # motif obligatoire
            self.assertTrue(warn.called)
            self.assertEqual(float(PC.get(pid).quantity), 30)


if __name__ == "__main__":
    unittest.main()
