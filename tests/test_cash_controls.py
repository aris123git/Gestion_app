"""Tests des plafonds remise / crédit caissier."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_cash_controls_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.category_controller import CategoryController  # noqa: E402
from app.controllers.client_controller import ClientController  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import (  # noqa: E402
    CartLine,
    PaymentLine,
    SaleController,
)
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import cash_controls, permissions as perms  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402


class CashControlsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cash_controls.set_limits(10, 5_000)
        cats = CategoryController.list()
        cls.product = ProductController.create(
            {
                "name": "Produit Plafond",
                "sale_price": 10_000,
                "purchase_price": 5_000,
                "quantity": 50,
                "category_id": cats[0].id if cats else None,
            }
        )
        cls.client = ClientController.create(
            {"name": "Client Plafond", "phone": "770000111"}
        )
        cls.cashier = AuthService.create_user(
            username="caissier_plafond",
            password="caissier1",
            full_name="Caissier Plafond",
            role=perms.ROLE_CASHIER,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_assert_blocks_high_discount(self) -> None:
        user = SimpleNamespace(role=perms.ROLE_CASHIER)
        with self.assertRaises(ValueError):
            cash_controls.assert_cashier_sale_limits(
                user=user, subtotal=10_000, discount=2_000, credit_amount=0
            )

    def test_assert_allows_admin(self) -> None:
        user = SimpleNamespace(role=perms.ROLE_ADMIN)
        cash_controls.assert_cashier_sale_limits(
            user=user, subtotal=10_000, discount=9_000, credit_amount=50_000
        )

    def test_create_sale_rejects_cashier_over_credit(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            SaleController.create_sale(
                [CartLine(self.product.id, self.product.name, 10_000, 1)],
                [PaymentLine(config.PAYMENT_METHOD_CREDIT, 10_000)],
                client_id=self.client.id,
                user_id=self.cashier.id,
                allow_credit=True,
            )
        self.assertIn("Dette trop élevée", str(ctx.exception))

    def test_create_sale_accepts_cashier_within_credit(self) -> None:
        # Produit 1000, crédit 4000 max wait - use partial: need cheaper or lower credit
        # Limit is 5000; sell 4000 worth... product is 10000. Use quantity fraction?
        # Create smaller sale via amount: 1 unit at 10000 is over. Use discount? 
        # Better: pay 6000 cash + 4000 credit = within 5000 credit.
        result = SaleController.create_sale(
            [CartLine(self.product.id, self.product.name, 10_000, 1)],
            [
                PaymentLine("Espèces", 6_000),
                PaymentLine(config.PAYMENT_METHOD_CREDIT, 4_000),
            ],
            amount_received=6_000,
            client_id=self.client.id,
            user_id=self.cashier.id,
            allow_credit=True,
        )
        self.assertTrue(result.sale_id)


if __name__ == "__main__":
    unittest.main()
