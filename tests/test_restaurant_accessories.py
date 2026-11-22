"""Plats composés avec accessoires rapides (Maquis) : attiéké, alloco, frites..."""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")

ACCESSORIES = [
    {"name": "Attiéké", "price": 300},
    {"name": "Alloco", "price": 200},
    {"name": "Frites", "price": 500},
]


class ProductAccessoriesModelTest(unittest.TestCase):
    def test_round_trip_and_garbage_json(self):
        from app.models.product import Product
        product = Product(name="Poisson braisé")
        self.assertEqual(product.accessories, [])
        product.set_accessories(ACCESSORIES + [{"name": "", "price": 100}, {"price": 50}])
        self.assertEqual(len(product.accessories), 3)
        self.assertEqual(product.accessories[0], {"name": "Attiéké", "price": 300.0})
        product.accessories_json = "{not json"
        self.assertEqual(product.accessories, [])


class RestaurantAccessoriesTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_accessories_")
        os.environ["GESTION_DATA_DIR"] = self._dir
        os.environ["NEXAGES_PRODUCT"] = "maquis"
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from app.database.connection import engine, init_database
        from app.database.seed import seed_all
        engine.dispose()
        init_database()
        seed_all()
        # Le panier Maquis persiste sur disque (clé "user_id"), partagé entre tests
        # tant que GESTION_DATA_DIR reste le même process (config.DATA_DIR est figé
        # au premier import) : on repart d'un panier vide à chaque test.
        from app.services import maquis_cart_store
        maquis_cart_store.clear_cart(None)

    def tearDown(self):
        from app.database.connection import engine
        from app.services import maquis_cart_store
        maquis_cart_store.clear_cart(None)
        engine.dispose()
        os.environ.pop("NEXAGES_PRODUCT", None)
        shutil.rmtree(self._dir, ignore_errors=True)

    def _plate(self):
        from app.controllers.product_controller import ProductController
        return ProductController.create({
            "name": "Poisson braisé", "sale_price": 1500, "purchase_price": 900,
            "quantity": 20, "min_stock": 2, "accessories": ACCESSORIES,
        })

    def test_controller_persists_and_updates_accessories(self):
        from app.controllers.product_controller import ProductController
        product = self._plate()
        reloaded = ProductController.get(product.id)
        self.assertEqual(len(reloaded.accessories), 3)
        ProductController.update(product.id, {"name": reloaded.name, "sale_price": 1500, "purchase_price": 900, "quantity": 20, "min_stock": 2, "accessories": ACCESSORIES[:1]})
        reloaded2 = ProductController.get(product.id)
        self.assertEqual(reloaded2.accessories, [{"name": "Attiéké", "price": 300.0}])

    def test_accessory_picker_dialog_total(self):
        from app.ui.dialogs.accessory_picker_dialog import AccessoryPickerDialog
        dialog = AccessoryPickerDialog("Poisson braisé", 1500, ACCESSORIES, "FCFA")
        dialog._checks[0][0].setChecked(True)  # Attiéké
        dialog._checks[2][0].setChecked(True)  # Frites
        self.assertEqual(dialog._unit_price(), 1500 + 300 + 500)
        dialog._confirm()
        self.assertEqual(dialog.quantity, 1.0)
        self.assertEqual({a["name"] for a in dialog.selected}, {"Attiéké", "Frites"})

    def test_catalog_panel_routes_product_with_accessories_to_picker(self):
        from app.ui.widgets.pos_catalog_panel import PosCatalogPanel

        product = self._plate()
        panel = PosCatalogPanel()
        received = []
        panel.product_combo_chosen.connect(lambda p, acc, qty: received.append((p.id, acc, qty)))

        class _FakeDialog:
            def __init__(self, *a, **k):
                self.selected = [ACCESSORIES[0], ACCESSORIES[2]]
                self.quantity = 2.0

            def exec(self):
                return True

        with patch("app.ui.dialogs.accessory_picker_dialog.AccessoryPickerDialog", _FakeDialog):
            panel._select_product(product)

        self.assertEqual(len(received), 1)
        pid, accessories, qty = received[0]
        self.assertEqual(pid, product.id)
        self.assertEqual(qty, 2.0)
        self.assertEqual({a["name"] for a in accessories}, {"Attiéké", "Frites"})
        # Le champ quantité clavier ne doit pas s'activer pour ce produit (il a des accessoires).
        self.assertIsNone(panel._pending_product)

    def test_pos_page_combo_builds_single_combined_line(self):
        from app.ui.pages.pos_page import POSPage
        from app.ui.state import AppState

        product = self._plate()
        state = AppState()
        state.can = lambda _p: True
        page = POSPage(state)
        page._maquis_add_combo(product, [ACCESSORIES[0], ACCESSORIES[2]], 1.0)
        self.assertEqual(len(page.cart), 1)
        line = page.cart[0]
        self.assertEqual(line.unit_price, 1500 + 300 + 500)
        self.assertIn("Poisson braisé", line.name)
        self.assertIn("Attiéké", line.name)
        self.assertIn("Frites", line.name)

    def test_order_detail_combo_adds_single_order_item(self):
        from app.services.table_service import TableService
        from app.services.order_service import OrderService
        from app.ui.pages.order_detail_page import OrderDetailPage
        from app.ui.state import AppState

        table = TableService.create(number="T2")
        order = OrderService.open_on_table(table.id)
        product = self._plate()
        state = AppState()
        state.can = lambda _p: True
        page = OrderDetailPage(state)
        page.load(order.id)

        page._on_product_combo(product, [ACCESSORIES[1]], 1.0)
        reloaded = OrderService.get(order.id)
        self.assertEqual(len(reloaded.items), 1)
        self.assertEqual(float(reloaded.items[0].unit_price), 1500 + 200)
        self.assertIn("Alloco", reloaded.items[0].product_name)


if __name__ == "__main__":
    unittest.main()
