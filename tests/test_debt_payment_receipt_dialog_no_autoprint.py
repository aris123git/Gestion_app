"""Dialogue reçu de règlement dette : plus d'impression automatique à l'ouverture."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_debt_receipt_dialog_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.ui.dialogs.debt_payment_receipt_dialog import DebtPaymentReceiptDialog  # noqa: E402


class DebtPaymentReceiptDialogNoAutoPrintTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_opening_dialog_does_not_print(self) -> None:
        with patch(
            "app.ui.dialogs.debt_payment_receipt_dialog.print_debt_payment"
        ) as mock_print:
            DebtPaymentReceiptDialog(
                client_name="Amadou Ba",
                amount=2500,
                payment_method="Espèces",
                remaining_after=0,
                note="Test",
                cashier="caissier",
                payment_id=42,
            )
            mock_print.assert_not_called()

    def test_clicking_print_button_prints_once(self) -> None:
        with patch(
            "app.ui.dialogs.debt_payment_receipt_dialog.print_debt_payment"
        ) as mock_print, patch(
            "app.ui.dialogs.debt_payment_receipt_dialog.info"
        ):
            mock_print.return_value.printed = True
            mock_print.return_value.message = "OK"
            dlg = DebtPaymentReceiptDialog(
                client_name="Amadou Ba",
                amount=2500,
                payment_method="Espèces",
                remaining_after=0,
                note="Test",
                cashier="caissier",
                payment_id=42,
            )
            dlg._print()
            mock_print.assert_called_once()


if __name__ == "__main__":
    unittest.main()
