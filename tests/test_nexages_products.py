"""Tests NexaGes : profil produit, avoirs, tables / commandes Maquis."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="nexages_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Pas de produit forcé via env pour tester le fichier.
os.environ.pop("NEXAGES_PRODUCT", None)

from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import (  # noqa: E402
    avoir_service,
    order_service,
    product_profile,
    table_service,
)


class ProductProfileTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def setUp(self) -> None:
        path = product_profile.profile_path()
        if path.exists():
            path.unlink()
        os.environ.pop("NEXAGES_PRODUCT", None)

    def test_set_and_get_maquis(self) -> None:
        self.assertFalse(product_profile.is_product_chosen())
        product_profile.set_product(product_profile.PRODUCT_MAQUIS)
        self.assertTrue(product_profile.is_product_chosen())
        self.assertTrue(product_profile.is_maquis())
        self.assertEqual(product_profile.product_label(), "Maquis Caisse")

    def test_nav_differs_by_product(self) -> None:
        # Import ici : la traduction des libellés requiert la table settings,
        # créée par setUpClass.
        from app.ui.main_window import build_nav_items

        product_profile.set_product(product_profile.PRODUCT_GESTION)
        gestion_labels = {item[0] for item in build_nav_items()}
        self.assertIn("Avoirs", gestion_labels)
        self.assertNotIn("Tables", gestion_labels)

        product_profile.set_product(product_profile.PRODUCT_MAQUIS)
        maquis_labels = {item[0] for item in build_nav_items()}
        self.assertIn("Tables", maquis_labels)
        self.assertIn("Commandes", maquis_labels)
        self.assertIn("Avoirs", maquis_labels)
        self.assertIn("Achats", maquis_labels)  # héritage Gestion

    def test_profit_loyalty_on_both_products(self) -> None:
        product_profile.set_product(product_profile.PRODUCT_GESTION)
        self.assertTrue(product_profile.supports_profit_loyalty())
        self.assertIn(
            "fidélité",
            product_profile.PRODUCT_DESCRIPTIONS[
                product_profile.PRODUCT_GESTION
            ].lower(),
        )
        product_profile.set_product(product_profile.PRODUCT_MAQUIS)
        self.assertTrue(product_profile.supports_profit_loyalty())
        self.assertIn(
            "fidélité",
            product_profile.PRODUCT_DESCRIPTIONS[
                product_profile.PRODUCT_MAQUIS
            ].lower(),
        )
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    def test_create_and_redeem(self) -> None:
        avoir = avoir_service.AvoirService.create(
            amount=5000, customer_name="Jean", reason="Geste"
        )
        self.assertEqual(float(avoir.amount_remaining), 5000)
        updated = avoir_service.AvoirService.redeem(avoir.id, 2000)
        self.assertEqual(float(updated.amount_remaining), 3000)
        self.assertIn("partiel", updated.status)


class MaquisTablesOrdersTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    def _free_table(self):
        table_service.TableService.ensure_defaults()
        return next(
            t for t in table_service.TableService.list() if t.status == "libre"
        )

    def _make_product(self, name: str, price: float = 1000, stock: float = 10):
        from app.controllers.product_controller import ProductController

        return ProductController.create(
            {
                "name": name,
                "purchase_price": price / 2,
                "sale_price": price,
                "quantity": stock,
            }
        )

    def test_defaults_and_open_order(self) -> None:
        free = self._free_table()
        order = order_service.OrderService.open_on_table(free.id)
        self.assertTrue(order.public_id.startswith("CMD-"))
        opens = order_service.OrderService.list_open()
        self.assertTrue(any(o.id == order.id for o in opens))
        order_service.OrderService.mark_paid(order.id)
        tables2 = table_service.TableService.list()
        t2 = next(t for t in tables2 if t.id == free.id)
        self.assertEqual(t2.status, "libre")

    def test_add_products_and_quantities(self) -> None:
        product = self._make_product("Bière Test", price=600, stock=5)
        free = self._free_table()
        order = order_service.OrderService.open_on_table(free.id)

        order = order_service.OrderService.add_product(order.id, product.id)
        order = order_service.OrderService.add_product(order.id, product.id)
        self.assertEqual(len(order.items), 1)  # fusion des quantités
        self.assertEqual(float(order.total), 1200)

        item_id = order.items[0].id
        order = order_service.OrderService.set_item_quantity(order.id, item_id, 4)
        self.assertEqual(float(order.total), 2400)

        # Stock max = 5 → 6 doit échouer.
        with self.assertRaises(ValueError):
            order_service.OrderService.set_item_quantity(order.id, item_id, 6)

        order = order_service.OrderService.remove_item(order.id, item_id)
        self.assertEqual(len(order.items), 0)
        self.assertEqual(float(order.total), 0)
        order_service.OrderService.cancel(order.id)

    def test_settle_records_sale_and_frees_table(self) -> None:
        from app.controllers.product_controller import ProductController
        from app.controllers.sale_controller import SaleController

        product = self._make_product("Sucrerie Test", price=500, stock=8)
        free = self._free_table()
        order = order_service.OrderService.open_on_table(free.id)
        order = order_service.OrderService.add_product(order.id, product.id)
        order = order_service.OrderService.add_product(order.id, product.id)

        # Commande vide refusée sur une autre table.
        other = self._free_table()
        empty = order_service.OrderService.open_on_table(other.id)
        with self.assertRaises(ValueError):
            order_service.OrderService.settle(empty.id)
        order_service.OrderService.cancel(empty.id)

        result = order_service.OrderService.settle(order.id)
        self.assertEqual(result.total, 1000)
        sale = SaleController.get(result.sale_id)
        self.assertIsNotNone(sale)
        self.assertEqual(sale.status, "completed")
        self.assertEqual(float(sale.total), 1000)

        # Stock déduit : 8 − 2 = 6.
        refreshed = ProductController.get(product.id)
        self.assertEqual(float(refreshed.quantity), 6)

        # Commande payée, table libérée.
        paid = order_service.OrderService.get(order.id)
        self.assertEqual(paid.status, "payée")
        tables = table_service.TableService.list()
        t2 = next(t for t in tables if t.id == free.id)
        self.assertEqual(t2.status, "libre")

        # Déjà clôturée → refus.
        with self.assertRaises(ValueError):
            order_service.OrderService.settle(order.id)


if __name__ == "__main__":
    unittest.main()
