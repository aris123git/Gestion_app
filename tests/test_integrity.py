"""Tests d'intégrité métier sans dépendance pytest."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import date

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_integrity_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.client_controller import ClientController  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.report_controller import ReportController  # noqa: E402
from app.controllers.sale_controller import (  # noqa: E402
    BelowMinPriceError,
    CartLine,
    PaymentLine,
    SaleController,
)
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.debt import Debt  # noqa: E402
from app.models.sale import Sale  # noqa: E402
from app.services import permissions as perms  # noqa: E402
from app.services.debt_service import DebtService  # noqa: E402
from app.services.loyalty_service import LoyaltyService  # noqa: E402
from app.database.connection import session_scope  # noqa: E402


class IntegrityTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cls._counter = 0

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def _next_name(self, prefix: str) -> str:
        type(self)._counter += 1
        return f"{prefix} {type(self)._counter}"

    def _create_product(
        self,
        *,
        sale_price: float = 100,
        min_price: float = 0,
        quantity: float = 20,
        purchase_price: float = 40,
    ):
        name = self._next_name("Produit test")
        return ProductController.create(
            {
                "name": name,
                "barcode": f"BAR{self._counter}",
                "reference": f"REF{self._counter}",
                "purchase_price": purchase_price,
                "sale_price": sale_price,
                "min_price": min_price,
                "quantity": quantity,
                "min_stock": 1,
                "is_active": True,
            }
        )

    def _create_client(self):
        name = self._next_name("Client test")
        return ClientController.create({"name": name, "phone": f"77000{self._counter}"})

    def test_min_price_rejects_below_floor(self) -> None:
        product = self._create_product(sale_price=150, min_price=120)

        with self.assertRaises(BelowMinPriceError):
            SaleController.create_sale(
                [CartLine(product.id, product.name, 100, 1)],
                [PaymentLine("Espèces", 100)],
                amount_received=100,
            )

    def test_discount_is_clamped_to_subtotal(self) -> None:
        product = self._create_product(sale_price=100)

        result = SaleController.create_sale(
            [CartLine(product.id, product.name, 100, 1)],
            [],
            discount=500,
        )

        self.assertEqual(result.total, 0)
        with session_scope() as session:
            sale = session.get(Sale, result.sale_id)
            self.assertIsNotNone(sale)
            self.assertEqual(float(sale.discount), 100)

    def test_overpay_is_rejected(self) -> None:
        product = self._create_product(sale_price=100)

        with self.assertRaises(ValueError):
            SaleController.create_sale(
                [CartLine(product.id, product.name, 100, 1)],
                [PaymentLine("Espèces", 101)],
                amount_received=101,
            )

    def test_client_delete_with_sales_is_blocked(self) -> None:
        client = self._create_client()
        product = self._create_product(sale_price=100)
        SaleController.create_sale(
            [CartLine(product.id, product.name, 100, 1)],
            [PaymentLine("Espèces", 100)],
            amount_received=100,
            client_id=client.id,
        )

        with self.assertRaises(ValueError):
            ClientController.delete(client.id)

    def test_cashier_has_credit_and_stock_permissions(self) -> None:
        cashier_permissions = perms.permissions_for(perms.ROLE_CASHIER)

        self.assertIn(perms.SELL_ON_CREDIT, cashier_permissions)
        self.assertIn(perms.MANAGE_STOCK, cashier_permissions)

    def test_client_debt_and_loyalty_batch_summaries(self) -> None:
        client = self._create_client()
        DebtService.create_debt(client.id, 125, note="Dette groupée")
        LoyaltyService.add_points_for_sale(client.id, 1000)

        debt_summary = DebtService.summaries_for_clients([client.id])[client.id]
        loyalty_balances = LoyaltyService.balances_for_clients([client.id])

        self.assertEqual(debt_summary["total_remaining"], 125)
        self.assertEqual(debt_summary["active_count"], 1)
        self.assertEqual(loyalty_balances[client.id], 10)

    def test_report_payments_exclude_credit_method(self) -> None:
        client = self._create_client()
        product = self._create_product(sale_price=200)
        SaleController.create_sale(
            [CartLine(product.id, product.name, 200, 1)],
            [PaymentLine(config.PAYMENT_METHOD_CREDIT, 200)],
            client_id=client.id,
            allow_credit=True,
        )

        report = ReportController.build(date.today(), date.today())
        payment_methods = {method for method, _amount in report["payments"]}

        self.assertNotIn(config.PAYMENT_METHOD_CREDIT, payment_methods)
        self.assertGreaterEqual(report["credit_sales"], 200)

    def test_debt_settlement_counts_in_cash_revenue(self) -> None:
        """Le règlement d'une dette alimente le CA encaissé du rapport."""
        client = self._create_client()
        product = self._create_product(sale_price=1000)
        SaleController.create_sale(
            [CartLine(product.id, product.name, 1000, 1)],
            [PaymentLine(config.PAYMENT_METHOD_CREDIT, 1000)],
            client_id=client.id,
            allow_credit=True,
        )
        before = ReportController.build(date.today(), date.today())
        ClientController.settle_debt(
            client.id, 1000, payment_method="Espèces"
        )
        after = ReportController.build(date.today(), date.today())
        self.assertGreaterEqual(
            after["debt_repayments"] - before["debt_repayments"], 1000
        )
        self.assertGreaterEqual(
            after["cash_revenue"] - before["cash_revenue"], 1000
        )

    def test_cancel_sale_with_debt_payment_is_blocked(self) -> None:
        client = self._create_client()
        product = self._create_product(sale_price=300)
        result = SaleController.create_sale(
            [CartLine(product.id, product.name, 300, 1)],
            [PaymentLine(config.PAYMENT_METHOD_CREDIT, 300)],
            client_id=client.id,
            allow_credit=True,
        )
        with session_scope() as session:
            debt = session.query(Debt).filter(Debt.sale_id == result.sale_id).one()
            debt_id = debt.id
        DebtService.pay_debt(debt_id, 100, payment_method="Espèces")

        with self.assertRaises(ValueError):
            SaleController.cancel_sale(result.sale_id)


if __name__ == "__main__":
    unittest.main()
