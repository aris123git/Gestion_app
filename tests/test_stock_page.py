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
        with mock.patch.object(stock_page, "info"), mock.patch.object(stock_page, "confirm", return_value=True), mock.patch.object(stock_page, "warn") as warn:
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

    def test_entry_without_cost_asks_confirmation(self):
        from unittest import mock
        from app.controllers.product_controller import ProductController as PC
        from app.ui.pages import stock_page
        from app.ui.state import AppState

        pid = PC.create({"name": "Sans coût", "sale_price": 1000, "purchase_price": 800, "quantity": 1}).id
        st = AppState()
        st.can = lambda _p: True
        page = stock_page.StockPage(st)
        page.refresh()
        page.product_search.setText("Sans coût")
        page._set_action("in")
        page.quantity.setValue(5)
        with mock.patch.object(stock_page, "confirm", return_value=False) as c, mock.patch.object(stock_page, "info"):
            page._save()
            self.assertTrue(c.called)
            self.assertEqual(float(PC.get(pid).quantity), 1)
        with mock.patch.object(stock_page, "confirm", return_value=True), mock.patch.object(stock_page, "info"):
            page._save()
            self.assertEqual(float(PC.get(pid).quantity), 6)

    def test_full_inventory_and_sheet(self):
        from pathlib import Path
        from unittest import mock
        from app.controllers.product_controller import ProductController as PC
        from app.printers.inventory_sheet import build_inventory_sheet
        from app.ui.pages import stock_page
        from app.ui.state import AppState

        a = PC.create({"name": "Inv A", "sale_price": 1000, "purchase_price": 800, "quantity": 10}).id
        b = PC.create({"name": "Inv B", "sale_price": 1000, "purchase_price": 800, "quantity": 5}).id
        st = AppState()
        st.can = lambda _p: True
        page = stock_page.StockPage(st)
        page.refresh()
        page.inv_search.setText("Inv ")
        rows = {page.inv_table.item(r, 0).text(): r for r in range(page.inv_table.rowCount())}
        page.inv_table.item(rows["Inv A"], 2).setText("8")
        page.inv_table.item(rows["Inv B"], 2).setText("5")
        self.assertEqual(page.inv_table.item(rows["Inv A"], 3).text(), "-2")
        self.assertEqual(page.inv_table.item(rows["Inv B"], 3).text(), "0")
        with mock.patch.object(stock_page, "confirm", return_value=True), mock.patch.object(stock_page, "info"):
            page._validate_inventory()
        self.assertEqual(float(PC.get(a).quantity), 8)
        self.assertEqual(float(PC.get(b).quantity), 5)
        out = Path(tempfile.mkdtemp()) / "inv.pdf"
        build_inventory_sheet([("Inv A", "kg", "8")], out, show_expected=True)
        self.assertGreater(out.stat().st_size, 500)

    def test_order_suggestion_by_supplier(self):
        from unittest import mock
        from app.controllers.product_controller import ProductController as PC
        from app.controllers.supplier_controller import SupplierController as SC
        from app.ui.pages import stock_page
        from app.ui.state import AppState
        from PySide6.QtCore import Qt

        sid = SC.create({"name": "Grossiste Z", "phone": "+22670000001"}).id
        a = PC.create({"name": "Huile cmd", "sale_price": 1000, "purchase_price": 800, "quantity": 2, "min_stock": 5, "supplier_id": sid}).id
        PC.create({"name": "Sucre cmd", "sale_price": 500, "purchase_price": 400, "quantity": 0, "min_stock": 0})
        PC.create({"name": "Sel plein", "sale_price": 500, "purchase_price": 400, "quantity": 50, "min_stock": 5})
        self.assertEqual(PC.get(a).supplier_id, sid)
        st = AppState()
        st.can = lambda _p: True
        page = stock_page.StockPage(st)
        page.refresh()
        names = [page.order_table.item(r, 1).text() for r in range(page.order_table.rowCount())]
        self.assertIn("Huile cmd", names)
        self.assertIn("Sucre cmd", names)
        self.assertNotIn("Sel plein", names)
        page.order_supplier.setCurrentIndex(page.order_supplier.findData(sid))
        self.assertEqual(page.order_table.rowCount(), 1)
        self.assertEqual(page.order_table.item(0, 4).text(), "8")  # 2*5-2
        page.order_table.item(0, 4).setText("10")
        text = page.order_text(page._order_lines())
        self.assertIn("Huile cmd × 10", text)
        page.order_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(page._order_lines(), [])
        page.order_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        with mock.patch("PySide6.QtGui.QDesktopServices.openUrl") as op:
            page._whatsapp_order()
            self.assertIn("wa.me/22670000001", op.call_args[0][0].toString())
            page._print_order()
            self.assertEqual(op.call_count, 2)


if __name__ == "__main__":
    unittest.main()
