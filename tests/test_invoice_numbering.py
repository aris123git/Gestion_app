"""Tests : numéros de facture séquentiels (00001, 00002…)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_invnum_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"

from app import config  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine, SaleController  # noqa: E402
from app.database.connection import engine, init_database, session_scope  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.sale import Sale  # noqa: E402
from app.services.invoice_numbering import invoice_number  # noqa: E402


class InvoiceNumberTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cls.pid = ProductController.create({"name": "A", "sale_price": 100, "purchase_price": 50, "quantity": 50}).id

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def _sale(self):
        r = SaleController.create_sale([CartLine(self.pid, "A", 100, 1)], [PaymentLine("Espèces", 100)], amount_received=100)
        with session_scope() as s:
            sale = s.get(Sale, r.sale_id)
            s.expunge(sale)
        return sale

    def test_sequential_and_stable(self) -> None:
        a, b = self._sale(), self._sale()
        na, nb = invoice_number(a), invoice_number(b)
        self.assertRegex(na, r"^\d{5}$")
        self.assertEqual(int(nb), int(na) + 1)
        self.assertEqual(invoice_number(a), na)  # stable

    def test_preview(self) -> None:
        from types import SimpleNamespace

        self.assertEqual(invoice_number(SimpleNamespace(ticket_number="APERCU")), "00001")


if __name__ == "__main__":
    unittest.main()
