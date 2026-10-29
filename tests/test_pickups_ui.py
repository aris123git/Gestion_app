"""Écrans des enlèvements : création, validation, livraison, clôture (sans fenêtres bloquantes)."""
import os, shutil, tempfile, unittest

_D = tempfile.mkdtemp(prefix="gestion_pkui_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from app.controllers.client_controller import ClientController  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.supplier_controller import SupplierController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import pickup_service as ps, settings_service  # noqa: E402
from app.ui.dialogs import pickups_dialog as pd  # noqa: E402
from app.ui.state import AppState  # noqa: E402


class PickupUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        init_database(); seed_all()
        cls.state = AppState(); cls.state.auth.login("admin", "admin")
        cls.product = ProductController.create({"name": "Gasoil UI", "sale_price": 800, "purchase_price": 700, "quantity": 0}).id
        cls.supplier = SupplierController.create({"name": "SONABHY"}).id
        cls.client = ClientController.create({"name": "Station UI", "phone": "70000020"}).id

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def test_edit_dialog_prefills_catalog_cost(self):
        d = pd.PickupEditDialog()
        d.supplier.setCurrentIndex(d.supplier.findData(self.supplier))
        d.table.cellWidget(0, 0).setCurrentIndex(d.table.cellWidget(0, 0).findData(self.product))
        d.table.cellWidget(0, 1).setValue(500)
        self.assertEqual(d.table.cellWidget(0, 2).value(), 700)      # prix d'achat du produit
        self.assertFalse(d.table.cellWidget(0, 2).isEnabled())
        d.use_catalog_cost.setChecked(False)
        d.table.cellWidget(0, 2).setValue(650)
        d._accept()
        self.assertEqual((d.lines[0].quantity, d.lines[0].unit_cost, d.supplier_id), (500, 650, self.supplier))

    def test_list_buttons_follow_status_and_delivery(self):
        pid = ps.create([ps.PickupLine(self.product, 100)], supplier_id=self.supplier)
        dlg = pd.PickupsDialog(self.state)
        dlg.table.selectRow(0)
        self.assertTrue(dlg.btn["validate"].isEnabled())
        self.assertFalse(dlg.btn["deliver"].isEnabled())
        ps.validate(pid)
        dlg._reload()
        dlg.table.selectRow(0)
        self.assertTrue(dlg.btn["deliver"].isEnabled())
        self.assertFalse(dlg.btn["edit"].isEnabled())
        # Livraison via la fenêtre dédiée
        d = pd.DeliverDialog(self.state, pid)
        d.client.set_client(self.client)
        d.table.cellWidget(0, 2).setValue(60)
        d._deliver()
        self.assertIsNotNone(d.sale_id)
        self.assertEqual(ps.remaining(pid)[0].left, 40)
        dlg._reload()
        dlg.table.selectRow(0)
        self.assertEqual(dlg.table.item(0, 6).text(), "40")
        c = pd.ClosePickupDialog(None, ps.remaining(pid))
        c.reason.setCurrentIndex(0)
        ps.close(pid, c.reason.currentText())
        dlg._reload()
        self.assertEqual(dlg._rows[0].status, "closed")

    def test_deliver_requires_client(self):
        pid = ps.create([ps.PickupLine(self.product, 10)], supplier_id=self.supplier)
        ps.validate(pid)
        d = pd.DeliverDialog(self.state, pid)
        from unittest import mock
        with mock.patch.object(pd, "warn") as w:
            d._deliver()
            self.assertTrue(w.called)
        self.assertIsNone(d.sale_id)

    def test_button_only_for_enterprise(self):
        from app.ui.pages.purchases_page import PurchasesPage
        page = PurchasesPage(self.state)
        settings_service.save_shop_info(shop_type="Boutique")
        page.refresh()
        self.assertTrue(page.pickups_button.isHidden())
        settings_service.save_shop_info(shop_type="Entreprise")
        page.refresh()
        self.assertFalse(page.pickups_button.isHidden())


if __name__ == "__main__":
    unittest.main()
