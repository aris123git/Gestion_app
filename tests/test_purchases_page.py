import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp()
os.environ["GESTION_DATA_DIR"] = _TMP

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from app.database.connection import init_database
from app.database.seed import seed_all

init_database()
seed_all()


class _Fake:
    def __init__(self, d):
        self.amount, self.method = d.amount, d.method

    def exec(self):
        return 1


class PurchasesPageTest(unittest.TestCase):
    def test_list_detail_pay_cancel(self):
        from app.controllers.product_controller import ProductController as PC
        from app.controllers.supplier_controller import SupplierController as SC
        from app.services.purchase_service import PurchaseLine, PurchaseService
        from app.services.supplier_debt_service import SupplierDebtService
        from app.ui.pages import purchases_page as mod
        from app.ui.state import AppState

        pid = PC.create({"name": "Riz ach", "sale_price": 1000, "purchase_price": 700, "quantity": 0}).id
        sid = SC.create({"name": "Fourn Ach"}).id
        pu = PurchaseService.create([PurchaseLine(pid, "Riz ach", 10, 700)], supplier_id=sid, invoice_number="F-1", amount_paid=2000)
        st = AppState()
        st.can = lambda _p: True
        page = mod.PurchasesPage(st)
        page.refresh()
        self.assertEqual(page.history.rowCount(), 1)
        page.history.setCurrentCell(0, 0)
        self.assertEqual(page.d_lines.rowCount(), 1)
        self.assertTrue(page.pay_button.isEnabled())
        self.assertEqual(page._remaining(pu.id), 5000)
        # paiement partiel du reste de CET achat
        real = mod.PayDialog
        with mock.patch.object(mod, "PayDialog", side_effect=lambda r, p=None: _Fake(real(r, p))), mock.patch.object(mod, "info"):
            page._pay()
        self.assertEqual(page._remaining(pu.id), 0)
        self.assertFalse(page.pay_button.isEnabled())
        # filtre "À payer" vide, puis annulation
        page._set_filter("due")
        self.assertEqual(page.history.rowCount(), 0)
        page._set_filter("all")
        page.history.setCurrentCell(0, 0)
        with mock.patch.object(mod, "confirm", return_value=True), mock.patch.object(mod, "info"):
            page._cancel_selected_purchase()
        page._set_filter("cancelled")
        self.assertEqual(page.history.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
