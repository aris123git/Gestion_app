"""Tests de résolution d'imprimante (cible absente → défaut système)."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")

from app.printers import thermal_printer  # noqa: E402


class ResolvePrinterNameTestCase(unittest.TestCase):
    def test_empty_preferred_uses_system_default(self) -> None:
        with mock.patch.object(thermal_printer, "default_printer", return_value=""):
            name, warning = thermal_printer.resolve_printer_name("")
        self.assertEqual(name, "")
        self.assertEqual(warning, "")

    def test_known_printer_kept(self) -> None:
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=["EPSON_TM_T20", "PDF"]
        ):
            name, warning = thermal_printer.resolve_printer_name("EPSON_TM_T20")
        self.assertEqual(name, "EPSON_TM_T20")
        self.assertEqual(warning, "")

    def test_case_insensitive_match(self) -> None:
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=["EPSON_TM_T20"]
        ):
            name, warning = thermal_printer.resolve_printer_name("epson_tm_t20")
        self.assertEqual(name, "EPSON_TM_T20")
        self.assertEqual(warning, "")

    def test_unknown_printer_falls_back_and_clears_setting(self) -> None:
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=["EPSON_TM_T20"]
        ), mock.patch.object(
            thermal_printer, "default_printer", return_value="EPSON_TM_T20"
        ), mock.patch.object(
            thermal_printer.settings_service,
            "get_setting",
            return_value="Imprimante_Fantome",
        ), mock.patch.object(
            thermal_printer.settings_service, "set_setting"
        ) as set_setting:
            name, warning = thermal_printer.resolve_printer_name("Imprimante_Fantome")
            set_setting.assert_any_call("printer_name", "")
        self.assertEqual(name, "")
        self.assertIn("introuvable", warning.lower())

    def test_empty_detection_list_probe_false_clears(self) -> None:
        """Liste vide + sonde négative → on n'insiste pas sur le fantôme."""
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=[]
        ), mock.patch.object(
            thermal_printer, "probe_printer_exists", return_value=False
        ), mock.patch.object(
            thermal_printer, "default_printer", return_value=""
        ), mock.patch.object(
            thermal_printer.settings_service,
            "get_setting",
            return_value="EPSON_FANTOME",
        ), mock.patch.object(
            thermal_printer.settings_service, "set_setting"
        ) as set_setting:
            name, warning = thermal_printer.resolve_printer_name("EPSON_FANTOME")
            set_setting.assert_any_call("printer_name", "")
        self.assertEqual(name, "")
        self.assertIn("introuvable", warning.lower())

    def test_empty_detection_list_probe_true_keeps(self) -> None:
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=[]
        ), mock.patch.object(
            thermal_printer, "probe_printer_exists", return_value=True
        ), mock.patch.object(
            thermal_printer.settings_service, "set_setting"
        ) as set_setting:
            name, warning = thermal_printer.resolve_printer_name("EPSON_TM_T20")
            set_setting.assert_not_called()
        self.assertEqual(name, "EPSON_TM_T20")
        self.assertEqual(warning, "")

    def test_empty_detection_list_probe_none_keeps_with_warning(self) -> None:
        """Si la détection échoue vraiment, on conserve le réglage avec avertissement."""
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=[]
        ), mock.patch.object(
            thermal_printer, "probe_printer_exists", return_value=None
        ), mock.patch.object(
            thermal_printer.settings_service, "set_setting"
        ) as set_setting:
            name, warning = thermal_printer.resolve_printer_name("EPSON_TM_T20")
            set_setting.assert_not_called()
        self.assertEqual(name, "EPSON_TM_T20")
        self.assertIn("vérifier", warning.lower())

    def test_system_default_ghost_warned(self) -> None:
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=["PDF"]
        ), mock.patch.object(
            thermal_printer, "default_printer", return_value="Imprimante_Morte"
        ):
            name, warning = thermal_printer.resolve_printer_name("")
        self.assertEqual(name, "")
        self.assertIn("par défaut du système", warning)

    def test_device_path_missing_falls_back(self) -> None:
        missing = "/dev/usb/lp_does_not_exist_xyz"
        self.assertFalse(Path(missing).exists())
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=[]
        ), mock.patch.object(
            thermal_printer.settings_service, "set_setting"
        ) as set_setting:
            name, warning = thermal_printer.resolve_printer_name(
                missing, clear_invalid=False
            )
            set_setting.assert_not_called()
        self.assertEqual(name, missing)
        self.assertIn("introuvable", warning.lower())

    def test_is_device_path(self) -> None:
        self.assertTrue(thermal_printer.is_device_path("/dev/usb/lp0"))
        self.assertTrue(thermal_printer.is_device_path("\\\\server\\printer"))
        self.assertFalse(thermal_printer.is_device_path("EPSON_TM_T20"))
        self.assertFalse(thermal_printer.is_device_path(""))

    def test_printer_is_available(self) -> None:
        known = ["A", "B"]
        self.assertTrue(thermal_printer.printer_is_available("", known))
        self.assertTrue(thermal_printer.printer_is_available("A", known))
        self.assertFalse(thermal_printer.printer_is_available("Z", known))
        with mock.patch.object(
            thermal_printer, "probe_printer_exists", return_value=False
        ):
            self.assertFalse(thermal_printer.printer_is_available("Z", []))
        with mock.patch.object(
            thermal_printer, "probe_printer_exists", return_value=None
        ):
            self.assertTrue(thermal_printer.printer_is_available("Z", []))

    def test_reads_setting_when_preferred_none(self) -> None:
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=["OK"]
        ), mock.patch.object(
            thermal_printer.settings_service, "get_setting", return_value="OK"
        ):
            name, warning = thermal_printer.resolve_printer_name(None)
        self.assertEqual(name, "OK")
        self.assertEqual(warning, "")

    def test_match_printer_in_list(self) -> None:
        self.assertEqual(
            thermal_printer.match_printer_in_list("pdf", ["PDF", "EPSON"]),
            "PDF",
        )
        self.assertEqual(
            thermal_printer.match_printer_in_list("X", ["PDF"]),
            "",
        )


if __name__ == "__main__":
    unittest.main()
