"""Tests pavé numérique quantité (Maquis / tablette)."""

from __future__ import annotations

import os
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_keypad_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.dialogs.numeric_keypad_dialog import NumericKeypadDialog  # noqa: E402


class NumericKeypadDialogTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_confirm_initial(self) -> None:
        dialog = NumericKeypadDialog(title="Attieke", subtitle="500", initial="1")
        dialog._confirm()
        self.assertEqual(dialog.value, 1.0)

    def test_replace_first_digit(self) -> None:
        dialog = NumericKeypadDialog(title="P", initial="1")
        dialog._digit("3")
        self.assertEqual(dialog._text, "3")
        dialog._digit("2")
        self.assertEqual(dialog._text, "32")
        dialog._confirm()
        self.assertEqual(dialog.value, 32.0)

    def test_delete_line_flag(self) -> None:
        dialog = NumericKeypadDialog(title="P", allow_delete_line=True)
        dialog._delete_line()
        self.assertTrue(dialog.deleted)
        self.assertIsNone(dialog.value)


if __name__ == "__main__":
    unittest.main()
