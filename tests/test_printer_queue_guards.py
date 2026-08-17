"""Tests des garde-fous d'impression (file d'attente Windows)."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")

from app.printers.thermal_printer import (  # noqa: E402
    windows_job_status_reason,
    windows_printer_status_reason,
)


class PrinterStatusGuardsTestCase(unittest.TestCase):
    def test_online_printer_has_no_reason(self) -> None:
        self.assertEqual(windows_printer_status_reason(0), "")
        self.assertEqual(windows_printer_status_reason(0x00000400), "")  # PRINTING

    def test_offline_and_paused_are_blocked(self) -> None:
        self.assertIn("hors ligne", windows_printer_status_reason(0x00000080))
        self.assertIn("en pause", windows_printer_status_reason(0x00000001))
        self.assertIn("plus de papier", windows_printer_status_reason(0x00000010))

    def test_job_offline_blocked(self) -> None:
        self.assertEqual(windows_job_status_reason(0), "")
        self.assertEqual(windows_job_status_reason(0x00000010), "")  # PRINTING
        self.assertEqual(windows_job_status_reason(0x00000020), "hors ligne")
        self.assertEqual(windows_job_status_reason(0x00000040), "plus de papier")


if __name__ == "__main__":
    unittest.main()
