"""Caisse : fenêtres « commande enregistrée » et session de caisse — nouvel
habillage visuel (bandeaux), logique de validation/écart inchangée."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class SavedOrderPromptDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_reprint_button_present_when_printing_enabled(self):
        from app.ui.dialogs.saved_order_prompt_dialog import SavedOrderPromptDialog
        dialog = SavedOrderPromptDialog("CMD-042", True, parent=None)
        dialog._reprint()
        self.assertTrue(dialog.reprint_requested)
        self.assertTrue(dialog.result())


class CashSessionDialogsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_open_session_reads_amount(self):
        from app.ui.dialogs.cash_session_dialog import OpenCashSessionDialog
        dialog = OpenCashSessionDialog()
        dialog.amount.setValue(15000)
        dialog._save()
        self.assertEqual(dialog.opening_float, 15000)

    def test_close_session_variance_updates_with_counted_amount(self):
        from app.ui.dialogs.cash_session_dialog import CloseCashSessionDialog
        dialog = CloseCashSessionDialog(1, expected=20000)
        self.assertIn("0", dialog.variance_label.text())
        dialog.counted.setValue(19500)
        self.assertIn("500", dialog.variance_label.text())


if __name__ == "__main__":
    unittest.main()
