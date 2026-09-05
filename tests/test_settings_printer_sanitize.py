"""Régression : Paramètres ne doit pas effacer l'imprimante thermique enregistrée."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import MethodType
from unittest import mock

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_printer_settings_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.printers import thermal_printer  # noqa: E402
from app.services import settings_service  # noqa: E402
from app.ui.pages.settings_page import SettingsPage  # noqa: E402


class SettingsPrinterSanitizeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def _sanitize(self, select: str, available: list, key: str = "printer_name"):
        holder = type("H", (), {})()
        holder._sanitize_printer_selection = MethodType(
            SettingsPage._sanitize_printer_selection, holder
        )
        return holder._sanitize_printer_selection(
            select, available, setting_key=key
        )

    def test_empty_list_keeps_saved_thermal_name(self) -> None:
        settings_service.set_setting("printer_name", "EPSON_TM_T20")
        with mock.patch.object(
            thermal_printer, "probe_printer_exists", return_value=False
        ):
            select, cleared = self._sanitize("EPSON_TM_T20", [])
        self.assertEqual(select, "EPSON_TM_T20")
        self.assertFalse(cleared)
        self.assertEqual(settings_service.get_setting("printer_name"), "EPSON_TM_T20")

    def test_known_list_keeps_matched_name(self) -> None:
        settings_service.set_setting("printer_name", "epson_tm_t20")
        select, cleared = self._sanitize(
            "epson_tm_t20", ["EPSON_TM_T20", "HP DeskJet"]
        )
        self.assertEqual(select, "EPSON_TM_T20")
        self.assertFalse(cleared)
        self.assertEqual(settings_service.get_setting("printer_name"), "epson_tm_t20")

    def test_known_list_clears_true_ghost(self) -> None:
        settings_service.set_setting("printer_name", "FANTOME")
        select, cleared = self._sanitize("FANTOME", ["EPSON_TM_T20"])
        self.assertEqual(select, "")
        self.assertTrue(cleared)
        self.assertEqual(settings_service.get_setting("printer_name"), "")

    def test_missing_device_path_clears(self) -> None:
        missing = "/dev/usb/lp_does_not_exist_xyz"
        self.assertFalse(Path(missing).exists())
        settings_service.set_setting("printer_name", missing)
        select, cleared = self._sanitize(missing, [])
        self.assertEqual(select, "")
        self.assertTrue(cleared)

    def test_fill_combo_skips_other_offline_printers(self) -> None:
        """Les hors ligne ne sont pas proposées, sauf le réglage courant."""
        from PySide6.QtWidgets import QApplication, QComboBox

        app = QApplication.instance() or QApplication([])
        holder = type("H", (), {})()
        holder._fill_printer_combo = MethodType(
            SettingsPage._fill_printer_combo, holder
        )
        combo = QComboBox()
        combo.setEditable(True)
        holder._fill_printer_combo(
            combo,
            "POS-80C",
            [],  # aucune en ligne proposée
            offline_names={"OldZombie", "POS-80C"},
        )
        # POS-80C est hors ligne mais réglage courant → une entrée marquée.
        labels = [combo.itemText(i) for i in range(combo.count())]
        self.assertIn("POS-80C (hors ligne)", labels)
        self.assertNotIn("OldZombie", labels)
        self.assertNotIn("OldZombie (hors ligne)", labels)
        self.assertEqual(combo.currentData(), "POS-80C")
        del app

    def test_fill_combo_does_not_reinject_db_ghost(self) -> None:
        from PySide6.QtWidgets import QApplication, QComboBox

        app = QApplication.instance() or QApplication([])
        holder = type("H", (), {})()
        holder._fill_printer_combo = MethodType(
            SettingsPage._fill_printer_combo, holder
        )
        combo = QComboBox()
        combo.setEditable(True)
        holder._fill_printer_combo(
            combo,
            "Imprimante_Fantome",
            ["POS-80C", "HP DeskJet"],
            offline_names=set(),
        )
        self.assertEqual(combo.currentData(), "")
        self.assertNotIn("Imprimante_Fantome", [
            combo.itemText(i) for i in range(combo.count())
        ])
        del app


if __name__ == "__main__":
    unittest.main()
