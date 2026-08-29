"""Tests : motif obligatoire pour l'annulation de vente."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_cancel_reason_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine, SaleController  # noqa: E402
from app.database.connection import engine, init_database, session_scope  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.sale import Sale  # noqa: E402
from app.utils.cancel_reason import count_letters, validate_cancel_reason  # noqa: E402


class CancelReasonTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        from app.controllers.category_controller import CategoryController

        cats = CategoryController.list()
        cls.product = ProductController.create(
            {
                "name": "Article Annulation",
                "sale_price": 1000,
                "purchase_price": 500,
                "quantity": 20,
                "category_id": cats[0].id if cats else None,
            }
        )

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_validate_requires_ten_letters(self) -> None:
        self.assertIsNone(validate_cancel_reason(""))
        self.assertIsNone(validate_cancel_reason("1234567890"))
        self.assertIsNone(validate_cancel_reason("........."))
        self.assertIsNone(validate_cancel_reason("erreur"))  # 6 lettres
        self.assertIsNone(validate_cancel_reason("abc def ghi"))  # 9
        ok = validate_cancel_reason("erreur de saisie")
        self.assertIsNotNone(ok)
        self.assertGreaterEqual(count_letters(ok), 10)

    def test_cancel_without_reason_raises(self) -> None:
        result = SaleController.create_sale(
            [CartLine(self.product.id, self.product.name, 1000, 1)],
            [PaymentLine("Espèces", 1000)],
            amount_received=1000,
            user_id=1,
        )
        with self.assertRaises(ValueError) as ctx:
            SaleController.cancel_sale(result.sale_id, reason="")
        self.assertIn("Motif", str(ctx.exception))
        with self.assertRaises(ValueError):
            SaleController.cancel_sale(result.sale_id, reason="court")

    def test_cancel_with_reason_persists(self) -> None:
        result = SaleController.create_sale(
            [CartLine(self.product.id, self.product.name, 1000, 1)],
            [PaymentLine("Espèces", 1000)],
            amount_received=1000,
            user_id=1,
        )
        motif = "Client a change d avis"
        SaleController.cancel_sale(
            result.sale_id, restock=True, user_id=1, reason=motif
        )
        with session_scope() as session:
            sale = session.get(Sale, result.sale_id)
            self.assertEqual(sale.status, "cancelled")
            self.assertEqual(sale.cancel_reason, motif.strip())


if __name__ == "__main__":
    unittest.main()
