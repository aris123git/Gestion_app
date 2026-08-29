"""Tests sessions de caisse."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_cash_session_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.category_controller import CategoryController  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine, SaleController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.cash_session_service import CashSessionService  # noqa: E402
from app.services import permissions as perms  # noqa: E402


class CashSessionTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cls.user = AuthService.create_user(
            username="caissier_sess",
            password="caissier1",
            full_name="Caissier Session",
            role=perms.ROLE_CASHIER,
        )
        cats = CategoryController.list()
        cls.product = ProductController.create(
            {
                "name": "Article Session",
                "sale_price": 2000,
                "purchase_price": 1000,
                "quantity": 20,
                "category_id": cats[0].id if cats else None,
            }
        )

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_open_close_with_variance(self) -> None:
        session = CashSessionService.open_session(self.user.id, 5000, username="x")
        self.assertTrue(session.is_open)
        SaleController.create_sale(
            [CartLine(self.product.id, self.product.name, 2000, 1)],
            [PaymentLine("Espèces", 2000)],
            amount_received=2000,
            user_id=self.user.id,
        )
        expected = CashSessionService.compute_expected(session.id)
        self.assertAlmostEqual(expected, 7000.0, places=2)
        closed = CashSessionService.close_session(
            session.id, counted=6900, note="manque 100", user_id=self.user.id
        )
        self.assertEqual(closed.status, "fermée")
        self.assertAlmostEqual(float(closed.variance), -100.0, places=2)

    def test_cannot_open_twice(self) -> None:
        CashSessionService.open_session(self.user.id, 1000)
        with self.assertRaises(ValueError):
            CashSessionService.open_session(self.user.id, 1000)
        open_sess = CashSessionService.get_open(self.user.id)
        CashSessionService.close_session(open_sess.id, counted=1000, user_id=self.user.id)


if __name__ == "__main__":
    unittest.main()
