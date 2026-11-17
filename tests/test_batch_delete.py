import os
import tempfile
import unittest
from unittest import mock

os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GESTION_DATA_DIR"] = tempfile.mkdtemp()

from PySide6.QtCore import QItemSelectionModel


class BatchDeleteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from app.database.connection import init_database
        from app.database.seed import seed_all
        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()

    def test_products_and_expenses_multi(self):
        from app.controllers.product_controller import ProductController as PC
        from app.ui.pages import products_page as mod
        from app.ui.state import AppState
        from app.ui.widgets import batch

        for n in ("Lot A", "Lot B", "Lot C"):
            PC.create({"name": n, "sale_price": 100, "purchase_price": 50, "quantity": 1})
        st = AppState()
        st.can = lambda _p: True
        page = mod.ProductsPage(st)
        page.refresh()
        names = [page.table.item(r, 0).text() for r in range(page.table.rowCount())]
        sm = page.table.selectionModel()
        for n in ("Lot A", "Lot B"):
            sm.select(page.table.model().index(names.index(n), 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.assertEqual(len(batch.selected_rows(page.table)), 2)
        with mock.patch.object(batch, "confirm", return_value=True) as c, mock.patch.object(batch, "info") as i:
            page._delete()
            print(i.call_args)
            self.assertIn("2 produits", c.call_args[0][1])
        after = [page.table.item(r, 0).text() for r in range(page.table.rowCount())]
        self.assertNotIn("Lot A", after)
        self.assertNotIn("Lot B", after)
        self.assertIn("Lot C", after)

    def test_failures_do_not_stop_batch(self):
        from app.ui.widgets import batch

        def act(i):
            if i == 2:
                raise ValueError("interdit")

        with mock.patch.object(batch, "confirm", return_value=True), mock.patch.object(batch, "info") as info:
            n = batch.run_batch(None, "{n} ?", [(1, "a"), (2, "b"), (3, "c")], act, "faits")
        self.assertEqual(n, 2)
        self.assertIn("interdit", info.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
