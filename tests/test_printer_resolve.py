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

    def test_pos80c_fuzzy_match(self) -> None:
        available = ["Microsoft Print to PDF", "POS-80C", "HP DeskJet"]
        self.assertEqual(
            thermal_printer.match_printer_in_list("POS 80C", available),
            "POS-80C",
        )
        self.assertEqual(
            thermal_printer.match_printer_in_list("pos80c", available),
            "POS-80C",
        )
        self.assertEqual(
            thermal_printer.match_printer_in_list("POS-80", available),
            "POS-80C",
        )

    def test_suggest_thermal_prefers_pos(self) -> None:
        available = ["Microsoft Print to PDF", "HP LaserJet", "POS-80C"]
        self.assertEqual(
            thermal_printer.suggest_thermal_printer(available),
            "POS-80C",
        )
        self.assertTrue(thermal_printer.is_likely_thermal_printer("POS 80C"))
        self.assertTrue(thermal_printer.is_virtual_printer("Microsoft Print to PDF"))
        self.assertFalse(thermal_printer.is_likely_thermal_printer("Microsoft Print to PDF"))

    def test_pick_windows_target_skips_pdf_default(self) -> None:
        available = ["Microsoft Print to PDF", "POS-80C"]
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=available
        ), mock.patch.object(
            thermal_printer,
            "default_printer",
            return_value="Microsoft Print to PDF",
        ):
            target, hint = thermal_printer._pick_windows_print_target("")
        self.assertEqual(target, "POS-80C")
        self.assertIn("POS-80C", hint)

    def test_pick_windows_target_honors_fuzzy_preferred(self) -> None:
        available = ["POS-80C", "HP DeskJet"]
        with mock.patch.object(
            thermal_printer, "list_printers", return_value=available
        ):
            target, hint = thermal_printer._pick_windows_print_target("POS 80C")
        self.assertEqual(target, "POS-80C")
        self.assertEqual(hint, "")


class ListPrintersDetailedTestCase(unittest.TestCase):
    def test_skips_pending_deletion(self) -> None:
        raw = [
            thermal_printer.DiscoveredPrinter("POS-80C", online=True),
            thermal_printer.DiscoveredPrinter(
                "OldPrinter", online=False, pending_deletion=True
            ),
        ]
        with mock.patch.object(
            thermal_printer, "_list_printers_posix", return_value=raw
        ), mock.patch.object(
            thermal_printer.sys, "platform", "linux"
        ):
            found = thermal_printer.list_printers_detailed()
        names = [p.name for p in found]
        self.assertEqual(names, ["POS-80C"])

    def test_include_offline_flag(self) -> None:
        raw = [
            thermal_printer.DiscoveredPrinter("POS-80C", online=True),
            thermal_printer.DiscoveredPrinter("HP DeskJet", online=False),
        ]
        with mock.patch.object(
            thermal_printer, "_list_printers_posix", return_value=raw
        ), mock.patch.object(
            thermal_printer.sys, "platform", "linux"
        ):
            all_names = thermal_printer.list_printers(include_offline=True)
            online_only = thermal_printer.list_printers(include_offline=False)
        self.assertEqual(all_names, ["POS-80C", "HP DeskJet"])
        self.assertEqual(online_only, ["POS-80C"])

    def test_marks_offline_status(self) -> None:
        raw = [
            thermal_printer.DiscoveredPrinter("POS-80C", online=False),
            thermal_printer.DiscoveredPrinter("PDF", online=True),
        ]
        with mock.patch.object(
            thermal_printer, "_list_printers_posix", return_value=raw
        ), mock.patch.object(
            thermal_printer.sys, "platform", "linux"
        ):
            found = {p.name: p.online for p in thermal_printer.list_printers_detailed()}
        self.assertFalse(found["POS-80C"])
        self.assertTrue(found["PDF"])

    def test_dedupe_similar_pos_names(self) -> None:
        names = ["POS 80C", "POS-80C", "POS80C (copie 1)", "HP DeskJet"]
        out = thermal_printer.dedupe_printer_names(names)
        keys = {thermal_printer.normalize_printer_key(n) for n in out}
        self.assertEqual(len(keys), 2)
        self.assertTrue(any("pos" in n.lower() for n in out))
        self.assertNotIn("POS80C (copie 1)", out)

    def test_ticket_combo_hides_virtual_and_prefers_thermal(self) -> None:
        names = [
            "Microsoft Print to PDF",
            "Fax",
            "POS-80C",
            "HP DeskJet 2700",
            "OneNote",
        ]
        ticket = thermal_printer.printers_for_ticket_combo(names)
        invoice = thermal_printer.printers_for_invoice_combo(names)
        self.assertEqual(ticket, ["POS-80C"])
        self.assertEqual(invoice, ["HP DeskJet 2700"])
        self.assertNotIn("Microsoft Print to PDF", ticket)
        self.assertNotIn("Fax", invoice)

if __name__ == "__main__":
    unittest.main()
