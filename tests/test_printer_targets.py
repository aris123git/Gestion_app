"""Tests résolution imprimante ticket vs facture encre."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_printer_targets_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.printers.half_a4_invoice import PAPER_HALF_A4  # noqa: E402
from app.printers.printer_targets import (  # noqa: E402
    describe_destinations,
    get_invoice_printer_name,
    get_thermal_printer_name,
    printer_for_paper,
    set_printers,
)
from app.services import settings_service  # noqa: E402


class PrinterTargetsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_thermal_and_invoice_separate(self) -> None:
        set_printers(thermal_name="EPSON TM-T20", invoice_name="HP DeskJet")
        self.assertEqual(get_thermal_printer_name(), "EPSON TM-T20")
        self.assertEqual(get_invoice_printer_name(), "HP DeskJet")
        self.assertEqual(printer_for_paper("80mm"), "EPSON TM-T20")
        self.assertEqual(printer_for_paper("58mm"), "EPSON TM-T20")
        self.assertEqual(printer_for_paper(PAPER_HALF_A4), "HP DeskJet")

    def test_invoice_falls_back_to_thermal(self) -> None:
        set_printers(thermal_name="Thermique Seule", invoice_name="")
        self.assertEqual(get_invoice_printer_name(), "Thermique Seule")
        self.assertEqual(printer_for_paper(PAPER_HALF_A4), "Thermique Seule")

    def test_describe_destinations(self) -> None:
        set_printers(thermal_name="T1", invoice_name="I1")
        thermal, invoice = describe_destinations()
        self.assertEqual(thermal, "T1")
        self.assertEqual(invoice, "I1")

    def test_settings_persist(self) -> None:
        set_printers(thermal_name="A", invoice_name="B")
        self.assertEqual(settings_service.get_setting("printer_name"), "A")
        self.assertEqual(settings_service.get_setting("invoice_printer_name"), "B")


if __name__ == "__main__":
    unittest.main()
