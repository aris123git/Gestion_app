"""Dialogue caisse : Imprimer = défaut Paramètres, sauf autre destination."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_ticket_dialog_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.printers.half_a4_invoice import PAPER_HALF_A4  # noqa: E402
from app.printers.printer_targets import (  # noqa: E402
    set_default_print_preference,
    set_printers,
)
from app.ui.dialogs.ticket_dialog import TicketDialog  # noqa: E402


class TicketDialogDefaultPrintTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def setUp(self) -> None:
        set_printers(thermal_name="THERMAL_X", invoice_name="INK_Y")
        self.sale = SimpleNamespace(ticket_number="T-UT-1", id=1, items=[])

    def _dialog(self) -> TicketDialog:
        with patch(
            "app.ui.dialogs.ticket_dialog.thermal_printer.render_ticket_text",
            return_value="APERCU",
        ):
            return TicketDialog(self.sale, auto_print=False)

    def test_print_starts_on_thermal_default(self) -> None:
        set_default_print_preference("thermique", "80mm")
        dlg = self._dialog()
        self.assertEqual(dlg._paper_value(), "80mm")
        self.assertIn("par défaut", dlg.destination.currentText())
        self.assertEqual(dlg.print_button.text(), "Imprimer le ticket")

    def test_can_switch_to_ink_when_thermal_default(self) -> None:
        set_default_print_preference("thermique", "80mm")
        with patch(
            "app.ui.dialogs.ticket_dialog.thermal_printer.render_ticket_text",
            return_value="APERCU",
        ):
            dlg = TicketDialog(self.sale, auto_print=False)
            for i in range(dlg.destination.count()):
                if dlg.destination.itemData(i) == PAPER_HALF_A4:
                    dlg.destination.setCurrentIndex(i)
                    break
            self.assertEqual(dlg._paper_value(), PAPER_HALF_A4)
            self.assertIn("encre", dlg.print_button.text().lower())

    def test_print_starts_on_ink_default(self) -> None:
        set_default_print_preference("encre")
        dlg = self._dialog()
        self.assertEqual(dlg._paper_value(), PAPER_HALF_A4)
        self.assertIn("par défaut", dlg.destination.currentText())
        self.assertIn("facture", dlg.print_button.text().lower())


if __name__ == "__main__":
    unittest.main()
