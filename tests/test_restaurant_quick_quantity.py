"""Saisie clavier de la quantité au Maquis : clic produit -> Entrée (ajout) -> Entrée (finalise)."""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class RestaurantQuickQuantityTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_quickqty_")
        os.environ["GESTION_DATA_DIR"] = self._dir
        os.environ["NEXAGES_PRODUCT"] = "maquis"
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from app.database.connection import engine, init_database
        from app.database.seed import seed_all
        engine.dispose()
        init_database()
        seed_all()

    def tearDown(self):
        from app.database.connection import engine
        engine.dispose()
        os.environ.pop("NEXAGES_PRODUCT", None)
        shutil.rmtree(self._dir, ignore_errors=True)

    def _product(self, **overrides):
        from app.controllers.product_controller import ProductController
        data = {"name": "Riz gras", "sale_price": 1500, "purchase_price": 900, "quantity": 50, "min_stock": 2}
        data.update(overrides)
        return ProductController.create(data)

    def test_click_then_two_enters_adds_then_finalizes(self):
        from app.ui.widgets.pos_catalog_panel import PosCatalogPanel

        product = self._product()
        panel = PosCatalogPanel()
        self.assertTrue(panel._maquis)
        # isHidden() ne dépend pas de l'affichage réel (pas de .show() ici, test offscreen).
        self.assertFalse(panel._quantity_row_widget.isHidden())

        received = []
        panel.product_quantity_chosen.connect(lambda p, q: received.append((p.id, q)))
        finalized = []
        panel.finalize_requested.connect(lambda: finalized.append(True))

        # Clic sur un produit : la quantité est en attente, le champ est prérempli à 1.
        panel._select_product(product)
        self.assertEqual(panel._pending_product.id, product.id)
        self.assertEqual(panel.quantity_input.text(), "1")

        # Le caissier tape une quantité puis Entrée : ajout au panier.
        panel.quantity_input.setText("3")
        panel._confirm_quantity()
        self.assertEqual(received, [(product.id, 3.0)])
        self.assertIsNone(panel._pending_product)

        # Entrée à nouveau, sans avoir recliqué sur un produit : finalise.
        panel._confirm_quantity()
        self.assertEqual(finalized, [True])
        self.assertEqual(len(received), 1)  # pas de second ajout

    def test_pos_page_merges_quantity_into_existing_line(self):
        from app.ui.pages.pos_page import PosPage
        from app.ui.state import AppState

        product = self._product()
        state = AppState()
        state.can = lambda _p: True
        page = PosPage(state)
        page._maquis_add_quantity(product, 2.0)
        page._maquis_add_quantity(product, 1.5)
        self.assertEqual(len(page.cart), 1)
        self.assertEqual(page.cart[0].quantity, 3.5)

    def test_pos_page_blocks_insufficient_stock(self):
        from app.ui.pages.pos_page import PosPage
        from app.ui.state import AppState

        product = self._product(quantity=1)
        state = AppState()
        state.can = lambda _p: True
        page = PosPage(state)
        page._maquis_add_quantity(product, 5.0)
        self.assertEqual(len(page.cart), 0)

    def test_order_detail_quantity_and_finalize_print(self):
        from unittest.mock import patch
        from app.services.table_service import TableService
        from app.services.order_service import OrderService
        from app.ui.pages.order_detail_page import OrderDetailPage
        from app.ui.state import AppState

        table = TableService.create(number="T1")
        order = OrderService.open_on_table(table.id)
        product = self._product()
        state = AppState()
        state.can = lambda _p: True
        page = OrderDetailPage(state)
        page.load(order.id)

        page._on_product_quantity(product, 4.0)
        lines = OrderService.get(order.id)
        self.assertEqual(len(lines.items), 1)
        self.assertEqual(lines.items[0].quantity, 4.0)

        with patch("app.ui.pages.order_detail_page.print_kitchen_for_order", return_value=(True, "ok")) as printer:
            page.catalog.finalize_requested.emit()
            printer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
