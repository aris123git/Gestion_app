"""Tests fidélité bénéfices : crédit → produit offert (pas d'argent)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_profit_loyalty_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ["NEXAGES_PRODUCT"] = "gestion"
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
        cls.reward = ProductController.create(
            {
                "name": "Frite Offerte",
                "sale_price": 500,
                "purchase_price": 200,
                "quantity": 200,
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

    def _sell_paid(self, qty: float = 1) -> object:
        line = CartLine(
            self.product.id,
            self.product.name,
            float(self.product.sale_price),
            qty,
            purchase_price=float(self.product.purchase_price),
        )
        return SaleController.create_sale(
            [line],
            [PaymentLine("Espèces", line.total)],
            amount_received=line.total,
            client_id=self.client.id,
            user_id=getattr(self.admin, "id", None),
        )

    def _sell_with_reward(self, reward_qty: float = 1) -> object:
        paid = CartLine(
            self.product.id,
            self.product.name,
            float(self.product.sale_price),
            1,
            purchase_price=float(self.product.purchase_price),
        )
        free = CartLine(
            self.reward.id,
            self.reward.name,
            float(self.reward.sale_price),
            reward_qty,
            purchase_price=float(self.reward.purchase_price),
            loyalty_reward=True,
        )
        # Total = paid only (free line total = 0).
        return SaleController.create_sale(
            [paid, free],
            [PaymentLine("Espèces", paid.total)],
            amount_received=paid.total,
            client_id=self.client.id,
            user_id=getattr(self.admin, "id", None),
        )

    def test_grants_avoir_when_profit_threshold_reached(self) -> None:
        before = ProfitLoyaltyService.credit_balance(self.client.id)
        for _ in range(5):
            self._sell_paid(1)
        after = ProfitLoyaltyService.credit_balance(self.client.id)
        self.assertAlmostEqual(after - before, 500.0, places=1)

    def test_cash_loyalty_param_does_not_discount(self) -> None:
        """Un loyalty_credit monétaire passé en paramètre est ignoré."""
        # Garantir un crédit.
        if ProfitLoyaltyService.credit_balance(self.client.id) < 500:
            for _ in range(5):
                self._sell_paid(1)
        before = ProfitLoyaltyService.credit_balance(self.client.id)
        line = CartLine(
            self.product.id,
            self.product.name,
            2_000,
            1,
            purchase_price=1_000,
        )
        result = SaleController.create_sale(
            [line],
            [PaymentLine("Espèces", 2_000)],
            amount_received=2_000,
            client_id=self.client.id,
            user_id=getattr(self.admin, "id", None),
            loyalty_credit=500,  # ne doit rien faire sans ligne loyalty_reward
        )
        self.assertEqual(result.total, 2_000)
        # Pas de consommation de crédit sans produit offert.
        self.assertAlmostEqual(
            ProfitLoyaltyService.credit_balance(self.client.id),
            before + 0,  # peut augmenter si nouveau palier, mais pas baisser de 500
            delta=600,
        )
        # Le crédit n'a pas baissé de 500 purement monétaire :
        after = ProfitLoyaltyService.credit_balance(self.client.id)
        self.assertGreaterEqual(after, before - 0.01)

    def test_product_reward_redeems_and_ticket_remaining(self) -> None:
        if ProfitLoyaltyService.credit_balance(self.client.id) < 500:
            for _ in range(5):
                self._sell_paid(1)
        before = ProfitLoyaltyService.credit_balance(self.client.id)
        result = self._sell_with_reward(1)
        after = ProfitLoyaltyService.credit_balance(self.client.id)
        # 500 consommé (prix frite), éventuel nouveau palier possible.
        self.assertLess(after, before)
        self.assertAlmostEqual(result.total, 2_000, places=1)
        if after > 0.01:
            self.assertIsNotNone(result.loyalty_credit_remaining)
            text = "\n".join(
                line.text
                for line in totals_block(
                    TicketData(
                        ticket_number="T",
                        moment=__import__("datetime").datetime.now(),
                        total=result.total,
                        loyalty_credit_remaining=result.loyalty_credit_remaining,
                        currency="FCFA",
                    ),
                    TicketOptions(),
                    42,
                )
            )
            self.assertIn("Reste crédit fidélité", text)

    def test_cannot_offer_product_above_credit(self) -> None:
        # Client sans crédit.
        other = ClientController.create({"name": "Sans Crédit", "phone": "771112233"})
        free = CartLine(
            self.reward.id,
            self.reward.name,
            500,
            1,
            purchase_price=200,
            loyalty_reward=True,
        )
        with self.assertRaises(ValueError):
            SaleController.create_sale(
                [free],
                [PaymentLine("Espèces", 0)],
                amount_received=0,
                client_id=other.id,
                user_id=getattr(self.admin, "id", None),
            )

    def test_ticket_hides_zero_remaining(self) -> None:
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
                "discount": 0,
                "total": 1000,
                "amount_received": 1000,
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
