"""Tests reçu de règlement de dette."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_debt_receipt_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.database.connection import init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.printers.thermal_printer import (  # noqa: E402
    render_debt_payment_text,
    save_debt_payment_file,
)


class DebtPaymentReceiptTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_render_contains_key_fields(self) -> None:
        text = render_debt_payment_text(
            client_name="Amadou Ba",
            amount=2500,
            payment_method="Espèces",
            remaining_after=0,
            note="Test",
            cashier="caissier",
            payment_id=42,
        )
        self.assertIn("RECU REGLEMENT DETTE", text)
        self.assertIn("Amadou Ba", text)
        self.assertIn("Espèces", text)
        self.assertIn("caissier", text)

    def test_save_file(self) -> None:
        config.ensure_directories()
        text = render_debt_payment_text(
            client_name="Test",
            amount=1000,
            payment_method="Espèces",
            remaining_after=500,
        )
        path = save_debt_payment_file(text, payment_id=7)
        self.assertTrue(path.exists())
        self.assertIn("dette_paye_7", path.name)


if __name__ == "__main__":
    unittest.main()
