"""Vente au montant libre (ex. poissonnerie : « 300 F de chinchard »)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_free_amount_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine, SaleController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.product import Product  # noqa: E402


class FreeAmountSaleTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def _chinchard(self, stock: float = 50.0) -> Product:
        """1 carton = 10 000 F, ~10 kg, vente 1 500 F/kg, montant libre."""
        return ProductController.create(
            {
                "name": "Chinchard test",
                "barcode": "",
                "reference": "CHIN",
                "purchase_price": 10_000,
                "sale_price": 1_500,
                "min_price": 0,
                "pack_content": 10,
                "quantity": stock,
                "min_stock": 1,
                "free_amount_sale": True,
                "is_active": True,
            }
        )

    def test_cost_per_sale_unit(self) -> None:
        product = self._chinchard()
        self.assertAlmostEqual(product.cost_per_sale_unit, 1_000.0)

    def test_cart_line_math_300f(self) -> None:
        """Client demande 300 F → 0,2 kg, coût 200 F, marge 100 F, stock −0,02."""
        amount = 300.0
        sale_price = 1_500.0
        qty = amount / sale_price
        line = CartLine(
            product_id=1,
            name="Chinchard — 300",
            unit_price=sale_price,
            quantity=qty,
            purchase_price=1_000.0,
            free_amount=True,
            amount=amount,
            pack_content=10.0,
        )
        self.assertAlmostEqual(line.total, 300.0)
        self.assertAlmostEqual(line.quantity, 0.2)
        self.assertAlmostEqual(line.stock_quantity, 0.02)
        self.assertAlmostEqual(line.line_profit, 100.0)

    def test_sale_deducts_carton_stock_and_records_profit(self) -> None:
        product = self._chinchard(stock=50.0)
        amount = 300.0
        sale_price = 1_500.0
        qty = amount / sale_price
        line = CartLine(
            product_id=product.id,
            name=f"{product.name} — 300",
            unit_price=sale_price,
            quantity=qty,
            purchase_price=float(product.cost_per_sale_unit),
            free_amount=True,
            amount=amount,
            pack_content=float(product.pack_content),
        )
        result = SaleController.create_sale(
            lines=[line],
            payments=[PaymentLine(method="Espèces", amount=300)],
            amount_received=300,
            discount=0,
            client_id=None,
            user_id=1,
        )
        self.assertEqual(result.total, 300.0)

        refreshed = ProductController.get(product.id)
        self.assertAlmostEqual(float(refreshed.quantity), 50.0 - 0.02, places=5)

        sale = SaleController.get(result.sale_id)
        self.assertIsNotNone(sale)
        item = sale.items[0]
        self.assertAlmostEqual(float(item.quantity), 0.2)
        self.assertAlmostEqual(float(item.line_total), 300.0)
        self.assertAlmostEqual(float(item.unit_price), 1_500.0)
        self.assertAlmostEqual(float(item.purchase_price), 1_000.0)
        # Marge estimée stockée au niveau vente
        self.assertAlmostEqual(float(sale.profit), 100.0)

    def test_cancel_restocks_cartons(self) -> None:
        product = self._chinchard(stock=10.0)
        amount = 1_500.0  # 1 kg → 0,1 carton
        line = CartLine(
            product_id=product.id,
            name=product.name,
            unit_price=1_500.0,
            quantity=1.0,
            purchase_price=1_000.0,
            free_amount=True,
            amount=amount,
            pack_content=10.0,
        )
        result = SaleController.create_sale(
            lines=[line],
            payments=[PaymentLine(method="Espèces", amount=amount)],
            amount_received=amount,
            discount=0,
            user_id=1,
        )
        mid = ProductController.get(product.id)
        self.assertAlmostEqual(float(mid.quantity), 9.9, places=5)

        SaleController.cancel_sale(result.sale_id, restock=True, user_id=1)
        after = ProductController.get(product.id)
        self.assertAlmostEqual(float(after.quantity), 10.0, places=5)


if __name__ == "__main__":
    unittest.main()
