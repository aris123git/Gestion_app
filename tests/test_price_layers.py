"""Tests : le nouveau prix s'applique après l'écoulement de l'ancien stock (FIFO)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_layers_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"

from app import config  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine, SaleController  # noqa: E402
from app.controllers.stock_controller import StockController  # noqa: E402
from app.database.connection import engine, init_database, session_scope  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.models.sale import SaleItem  # noqa: E402
from app.services import price_layers  # noqa: E402


def _prices(pid):
    with session_scope() as s:
        p = s.get(Product, pid)
        return float(p.purchase_price), float(p.sale_price), float(p.quantity), price_layers.summary(s, pid)


def _sell(pid, qty, price):
    return SaleController.create_sale([CartLine(pid, "P", price, qty)], [PaymentLine("Espèces", price * qty)], amount_received=price * qty)


class PriceLayersTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def _product(self, qty=10):
        return ProductController.create({"name": f"P{os.urandom(3).hex()}", "sale_price": 150, "purchase_price": 100, "quantity": qty}).id

    def test_new_prices_wait_for_old_stock(self) -> None:
        pid = self._product(10)
        StockController.stock_in(pid, 10, 120, "Achat", None, new_sale_price=180)
        cost, sale, qty, layers = _prices(pid)
        self.assertEqual((cost, sale, qty), (100, 150, 20))
        self.assertEqual(len(layers), 1)
        _sell(pid, 9, 150)
        cost, sale, _q, _l = _prices(pid)
        self.assertEqual((cost, sale), (100, 150))  # il reste 1 ancienne unité
        _sell(pid, 1, 150)
        cost, sale, qty, layers = _prices(pid)
        self.assertEqual((cost, sale, qty, layers), (120, 180, 10, []))

    def test_immediate_when_no_old_stock(self) -> None:
        pid = self._product(0)
        StockController.stock_in(pid, 5, 130, "Achat", None, new_sale_price=200)
        cost, sale, _q, layers = _prices(pid)
        self.assertEqual((cost, sale, layers), (130, 200, []))

    def test_fifo_cost_on_mixed_sale(self) -> None:
        pid = self._product(10)
        StockController.stock_in(pid, 10, 120, "Achat", None)
        result = _sell(pid, 12, 150)
        with session_scope() as s:
            item = s.query(SaleItem).filter_by(sale_id=result.sale_id).one()
            self.assertAlmostEqual(float(item.purchase_price), (10 * 100 + 2 * 120) / 12, places=2)
        self.assertEqual(_prices(pid)[0], 120)

    def test_scheduled_price_change_from_product_form(self) -> None:
        pid = self._product(5)
        ProductController.update(pid, {"name": "X", "sale_price": 200, "purchase_price": 100, "quantity": 5, "price_timing": "after_stock"})
        self.assertEqual(_prices(pid)[1], 150)
        _sell(pid, 5, 150)
        self.assertEqual(_prices(pid)[1], 200)


if __name__ == "__main__":
    unittest.main()
