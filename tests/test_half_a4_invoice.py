"""Tests facture demi-A4 (PDF 210×148,5 mm)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_half_a4_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.printers.half_a4_invoice import (  # noqa: E402
    HALF_A4_SIZE,
    PAPER_HALF_A4,
    build_invoice_pdf,
    is_half_a4,
)
from app.printers.thermal_printer import render_ticket_text  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402


class HalfA4InvoiceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def _fake_sale(self):
        item = SimpleNamespace(
            product_name="Chinchard",
            quantity=0.2,
            unit_price=1500,
            line_total=300,
        )
        return SimpleNamespace(
            ticket_number="T-TEST-001",
            date=datetime(2026, 8, 29, 14, 30),
            cashier_name="Caissier",
            client_id=None,
            client_name="",
            items=[item],
            subtotal=300,
            discount=0,
            total=300,
            amount_received=300,
            change_due=0,
            payments=[SimpleNamespace(method="Espèces", amount=300)],
        )

    def test_format_detection(self) -> None:
        self.assertTrue(is_half_a4("demi-A4"))
        self.assertTrue(is_half_a4("A4/2"))
        self.assertTrue(is_half_a4(PAPER_HALF_A4))
        self.assertFalse(is_half_a4("80mm"))

    def test_page_size_is_half_a4(self) -> None:
        width, height = HALF_A4_SIZE
        self.assertAlmostEqual(width / mm, 210.0, places=1)
        self.assertAlmostEqual(height / mm, 148.5, places=1)

    def test_build_pdf_creates_file(self) -> None:
        sale = self._fake_sale()
        path = build_invoice_pdf(sale)
        self.assertTrue(path.exists())
        self.assertEqual(path.suffix.lower(), ".pdf")
        self.assertGreater(path.stat().st_size, 500)

    def test_preview_text_mentions_facture(self) -> None:
        sale = self._fake_sale()
        text = render_ticket_text(sale, paper="demi-A4")
        self.assertIn("FACTURE", text)
        self.assertIn("demi-A4", text)
        self.assertIn("300", text)


if __name__ == "__main__":
    unittest.main()
