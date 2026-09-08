"""Tests fidélité bénéfices (seuil admin → crédit avoir → ticket reste)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_profit_loyalty_")
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
from app.printers.ticket.data import TicketData  # noqa: E402
from app.printers.ticket.designs.base import totals_block  # noqa: E402
from app.printers.ticket.options import TicketOptions  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.profit_loyalty_service import ProfitLoyaltyService  # noqa: E402


class ProfitLoyaltyTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cats = CategoryController.list()
        cls.product = ProductController.create(
            {
                "name": "Boisson Fidélité",
                "sale_price": 2_000,
                "purchase_price": 1_000,
                "quantity": 500,
                "category_id": cats[0].id if cats else None,
            }
        )
        cls.client = ClientController.create(
            {"name": "Client Fidèle", "phone": "770001234"}
        )
        admins = [
            u for u in AuthService.list_users() if u.role == "Administrateur"
        ]
        cls.admin = admins[0] if admins else None
        ProfitLoyaltyService.set_config(
            enabled=True,
            threshold=5_000,
            percent=10,
            user_id=getattr(cls.admin, "id", None),
            username="admin",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def _sell(self, qty: float, *, loyalty: float = 0) -> object:
        line = CartLine(
            self.product.id,
            self.product.name,
            float(self.product.sale_price),
            qty,
            purchase_price=float(self.product.purchase_price),
        )
        total = round(line.total - loyalty, 2)
        return SaleController.create_sale(
            [line],
            [PaymentLine("Espèces", max(0.0, total))],
            amount_received=max(0.0, total),
            client_id=self.client.id,
            user_id=getattr(self.admin, "id", None),
            loyalty_credit=loyalty,
        )

    def test_grants_avoir_when_profit_threshold_reached(self) -> None:
        # Marge 1000 / unité → 5 ventes de 1 = 5000 bénéfice → 1 palier → 500 crédit.
        before = ProfitLoyaltyService.credit_balance(self.client.id)
        for _ in range(5):
            self._sell(1)
        after = ProfitLoyaltyService.credit_balance(self.client.id)
        self.assertAlmostEqual(after - before, 500.0, places=1)
        summary = ProfitLoyaltyService.client_summary(self.client.id)
        self.assertGreaterEqual(summary["profit_total"], 5_000)
        self.assertGreaterEqual(summary["purchase_total"], 10_000)

    def test_redeem_subtracts_and_ticket_remaining_only_if_positive(self) -> None:
        # Garantir un crédit.
        if ProfitLoyaltyService.credit_balance(self.client.id) < 500:
            for _ in range(5):
                self._sell(1)
        balance = ProfitLoyaltyService.credit_balance(self.client.id)
        self.assertGreater(balance, 0)

        # Utiliser une partie → reste sur ticket.
        use = min(200.0, balance - 1) if balance > 1 else balance
        if use <= 0:
            self.skipTest("pas de crédit à consommer partiellement")
        result = self._sell(1, loyalty=use)
        self.assertIsNotNone(result.loyalty_credit_remaining)
        self.assertGreater(result.loyalty_credit_remaining, 0.01)

        data = TicketData(
            ticket_number="T-test",
            moment=__import__("datetime").datetime.now(),
            discount=use,
            total=2_000 - use,
            loyalty_credit_remaining=result.loyalty_credit_remaining,
            currency="FCFA",
        )
        opts = TicketOptions()
        text = "\n".join(line.text for line in totals_block(data, opts, 42))
        self.assertIn("Reste remise fidélité", text)

        # Tout consommer → rien sur le ticket.
        left = ProfitLoyaltyService.credit_balance(self.client.id)
        if left <= 0:
            return
        # Vente assez grande pour absorber tout le crédit.
        qty = max(1, int((left / 1000) + 1))
        result2 = self._sell(qty, loyalty=left)
        self.assertIsNone(result2.loyalty_credit_remaining)
        data2 = TicketData(
            ticket_number="T-test2",
            moment=__import__("datetime").datetime.now(),
            discount=left,
            total=max(0.0, qty * 2000 - left),
            loyalty_credit_remaining=None,
            currency="FCFA",
        )
        text2 = "\n".join(line.text for line in totals_block(data2, opts, 42))
        self.assertNotIn("Reste remise fidélité", text2)

    def test_ticket_from_sale_hides_zero_remaining(self) -> None:
        sale = type(
            "S",
            (),
            {
                "ticket_number": "T1",
                "date": __import__("datetime").datetime.now(),
                "cashier_name": "Admin",
                "client_name": "X",
                "client_id": self.client.id,
                "items": [],
                "subtotal": 1000,
                "discount": 100,
                "total": 900,
                "amount_received": 900,
                "change_due": 0,
                "payments": [],
                "loyalty_credit_remaining": 0,
            },
        )()
        data = TicketData.from_sale(sale)
        self.assertIsNone(data.loyalty_credit_remaining)
        self.assertFalse(data.has_loyalty_credit_remaining)


if __name__ == "__main__":
    unittest.main()
