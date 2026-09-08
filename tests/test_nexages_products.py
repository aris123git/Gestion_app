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
from app.ui.main_window import build_nav_items  # noqa: E402


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

    def test_defaults_and_open_order(self) -> None:
        table_service.TableService.ensure_defaults()
        tables = table_service.TableService.list()
        self.assertGreaterEqual(len(tables), 1)
        free = next(t for t in tables if t.status == "libre")
        order = order_service.OrderService.open_on_table(free.id)
        self.assertTrue(order.public_id.startswith("CMD-"))
        opens = order_service.OrderService.list_open()
        self.assertTrue(any(o.id == order.id for o in opens))
        order_service.OrderService.mark_paid(order.id)
        tables2 = table_service.TableService.list()
        t2 = next(t for t in tables2 if t.id == free.id)
        self.assertEqual(t2.status, "libre")


if __name__ == "__main__":
    unittest.main()
