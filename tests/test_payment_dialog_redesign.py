"""Dialogue de paiement : nouvelle présentation (bandeau total, cartes de modes,
bandeau de résumé) — vérifie que la logique de calcul reste intacte."""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class PaymentDialogRedesignTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_payment_dialog_")
        os.environ["GESTION_DATA_DIR"] = self._dir
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from app.database.connection import engine, init_database
        from app.database.seed import seed_all
        engine.dispose()
        init_database()
        seed_all()

    def tearDown(self):
        from app.database.connection import engine
        engine.dispose()
        shutil.rmtree(self._dir, ignore_errors=True)

    def _dialog(self, **kwargs):
        from app.ui.dialogs.payment_dialog import PaymentDialog
        return PaymentDialog(45500, **kwargs)

    def test_method_cards_built_for_each_payment_method(self):
        from app import config
        dialog = self._dialog()
        self.assertEqual(set(dialog.method_cards.keys()), set(config.PAYMENT_METHODS))
        for card in dialog.method_cards.values():
            self.assertEqual(card.objectName(), "SmallCard")

    def test_cash_card_becomes_active_when_amount_entered(self):
        dialog = self._dialog()
        cash_spin = dialog.method_inputs["Espèces"]
        cash_spin.setValue(45500)
        self.assertEqual(dialog.method_cards["Espèces"].objectName(), "SmallCardActive")
        cash_spin.setValue(0)
        self.assertEqual(dialog.method_cards["Espèces"].objectName(), "SmallCard")

    def test_credit_card_hidden_when_credit_not_allowed(self):
        dialog = self._dialog(allow_credit=False)
        # isHidden() ne dépend pas de .show() (test offscreen) : on vérifie l'état explicite.
        self.assertTrue(dialog.credit_card.isHidden())

    def test_summary_reflects_cash_and_change(self):
        dialog = self._dialog()
        dialog.method_inputs["Espèces"].setValue(45500)
        dialog.received_input.setValue(50000)
        dialog._recalculate()
        text = dialog.summary.text()
        self.assertIn("45 500", text.replace(" ", " ").replace("\xa0", " "))
        self.assertTrue(dialog.validate.isEnabled())

    def test_confirm_still_produces_payment_lines(self):
        dialog = self._dialog()
        dialog.method_inputs["Espèces"].setValue(45500)
        dialog.received_input.setValue(45500)
        dialog._confirm()
        self.assertEqual(len(dialog.result_payments), 1)
        self.assertEqual(dialog.result_payments[0].method, "Espèces")
        self.assertEqual(dialog.result_payments[0].amount, 45500)


if __name__ == "__main__":
    unittest.main()
