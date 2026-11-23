"""Caisse : vérifie que les petites fenêtres pop-up redessinées (montant libre,
changement de prix) gardent leur logique après la mise à jour visuelle."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class FreeAmountDialogRedesignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_choosing_a_preset_sets_amount_and_accepts(self):
        from app.ui.dialogs.free_amount_dialog import FreeAmountDialog
        dialog = FreeAmountDialog("Essence", 1000)
        dialog._choose(300)
        self.assertEqual(dialog.amount, 300)
        self.assertTrue(dialog.result())

    def test_custom_amount_requires_positive_value(self):
        from app.ui.dialogs.free_amount_dialog import FreeAmountDialog
        dialog = FreeAmountDialog("Essence", 1000)
        self.assertFalse(dialog.ok.isEnabled())
        dialog.custom.setValue(500)
        self.assertTrue(dialog.ok.isEnabled())
        dialog._confirm_custom()
        self.assertEqual(dialog.amount, 500)


class PriceChangeDialogRedesignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_default_choice_is_once(self):
        from app.ui.dialogs.price_change_dialog import PriceChangeDialog
        dialog = PriceChangeDialog("Riz 5kg")
        dialog._confirm()
        self.assertEqual(dialog.choice, "once")

    def test_permanent_choice(self):
        from app.ui.dialogs.price_change_dialog import PriceChangeDialog
        dialog = PriceChangeDialog("Riz 5kg")
        dialog.option_perm.setChecked(True)
        dialog._confirm()
        self.assertEqual(dialog.choice, "permanent")

    def test_cancel_button_rejects(self):
        from app.ui.dialogs.price_change_dialog import PriceChangeDialog
        dialog = PriceChangeDialog("Riz 5kg")
        dialog.reject()
        self.assertFalse(dialog.result())


if __name__ == "__main__":
    unittest.main()
