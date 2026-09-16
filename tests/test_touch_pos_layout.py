"""Caisse tactile Maquis : mêmes composants de saisie qu'à la table."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="maquis_touch_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["NEXAGES_PRODUCT"] = "maquis_caisse"

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import catalog_features, product_profile  # noqa: E402
from app.services.order_service import OrderService  # noqa: E402
from app.services.table_service import TableService  # noqa: E402
from app.ui.pages.order_entry import OrderEntryDialog  # noqa: E402
from app.ui.pages.pos_page import POSPage  # noqa: E402
from app.ui.state import AppState  # noqa: E402
from app.ui.widgets.touch_catalog import TouchCatalog  # noqa: E402
from app.ui.widgets.touch_ticket import TouchTicket  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _silence_dialogs() -> None:
    """Neutralise les boîtes modales : un test ne doit jamais attendre un clic."""
    from app.ui.pages import order_entry, pos_page

    for module in (pos_page, order_entry):
        module.warn = lambda *args, **kwargs: None
        module.info = lambda *args, **kwargs: None
    order_entry.confirm = lambda *args, **kwargs: True


class TouchLayoutTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        _silence_dialogs()
        cls.state = AppState()
        cls.state.auth.login("admin", "admin")
        cls.product = ProductController.create(
            {
                "name": "Sucrerie tactile",
                "purchase_price": 300,
                "sale_price": 500,
                "quantity": 20,
                "min_stock": 2,
                "is_active": True,
            }
        )

    @classmethod
    def tearDownClass(cls) -> None:
        os.environ.pop("NEXAGES_PRODUCT", None)
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def setUp(self) -> None:
        # D'autres modules de test remettent le produit à zéro : on le force ici.
        os.environ["NEXAGES_PRODUCT"] = "maquis_caisse"

    def test_touch_layout_default_for_maquis(self) -> None:
        self.assertTrue(product_profile.is_maquis())
        self.assertTrue(catalog_features.touch_layout_enabled())

    def test_pos_uses_touch_catalog_and_ticket(self) -> None:
        page = POSPage(self.state)
        page.refresh()
        self.assertIsInstance(page._touch_catalog, TouchCatalog)
        self.assertIsInstance(page.touch_ticket, TouchTicket)
        self.assertFalse(hasattr(page, "cart_table"))

        # Un appui sur la tuile produit remplit le panier et l'ardoise tactile.
        page._add_product_by_id(self.product.id)
        self.assertEqual(len(page.cart), 1)
        self.assertEqual(len(page.touch_ticket._rows), 1)
        # Le stock affiché tient compte du panier en cours.
        tile = next(
            t for t in page._touch_catalog._tiles if t.product_id == self.product.id
        )
        self.assertIn("19", tile._stock_label.text())

        # « + » puis pavé : la quantité passe par le même chemin de validation.
        page._set_line_quantity(0, 3)
        self.assertEqual(float(page.cart[0].quantity), 3)
        page._set_line_quantity(0, 999)  # au-delà du stock : refusé
        self.assertEqual(float(page.cart[0].quantity), 3)
        page._remove_line(0)
        self.assertEqual(page.cart, [])
        page.deleteLater()

    def test_table_order_screen_uses_same_components(self) -> None:
        TableService.ensure_defaults()
        table = TableService.list()[0]
        order = OrderService.open_on_table(table.id)
        dialog = OrderEntryDialog(self.state, order.id)
        self.assertIsInstance(dialog.catalog, TouchCatalog)
        self.assertIsInstance(dialog.ticket, TouchTicket)

        dialog._add_product_by_id(self.product.id)
        refreshed = OrderService.get(order.id)
        self.assertEqual(len(refreshed.items), 1)
        self.assertEqual(len(dialog.ticket._rows), 1)
        self.assertIn("500", dialog.total_label.text())

        dialog._on_quantity_changed(0, 4)
        self.assertEqual(float(OrderService.get(order.id).total), 2_000)
        dialog.deleteLater()
        OrderService.cancel(order.id)


if __name__ == "__main__":
    unittest.main()
