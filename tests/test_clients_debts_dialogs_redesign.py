"""Clients / Dettes : nouvel habillage visuel (bandeaux + cartes) des fenêtres
pop-up — vérifie que la logique de ces dialogues reste intacte."""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class _DBTestCase(unittest.TestCase):
    """Base : certains de ces dialogues lisent la devise en base."""

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_clients_dialogs_")
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


class DebtPaymentDialogTest(_DBTestCase):
    def test_pay_all_fills_amount_and_save_builds_result(self):
        from app.ui.dialogs.debt_payment_dialog import DebtPaymentDialog
        dialog = DebtPaymentDialog("Awa Traoré", 15000)
        dialog.amount.setValue(15000)
        dialog._save()
        self.assertEqual(dialog.result_data["amount"], 15000)


class ManualDebtDialogTest(_DBTestCase):
    def test_requires_positive_amount(self):
        from app.ui.dialogs.manual_debt_dialog import ManualDebtDialog
        dialog = ManualDebtDialog()
        dialog.amount.setValue(0)
        from unittest.mock import patch
        with patch("app.ui.dialogs.manual_debt_dialog.warn") as warn_box:
            dialog._save()
            warn_box.assert_called_once()
        self.assertIsNone(dialog.result_data)


class AuthorizeDialogTest(_DBTestCase):
    def test_wrong_credentials_warn_and_stay_open(self):
        from app.ui.dialogs.authorize_dialog import AuthorizeDialog
        from unittest.mock import patch
        dialog = AuthorizeDialog("Annulation de vente")
        dialog.username.setText("admin")
        dialog.password.setText("wrong")
        with patch("app.ui.dialogs.authorize_dialog.warn") as warn_box:
            dialog._authorize()
            warn_box.assert_called_once()
        self.assertEqual(dialog.authorized_username, "")

    def test_correct_credentials_accept(self):
        from app.ui.dialogs.authorize_dialog import AuthorizeDialog
        dialog = AuthorizeDialog("Annulation de vente")
        dialog.username.setText("admin")
        dialog.password.setText("admin")
        dialog._authorize()
        self.assertEqual(dialog.authorized_username, "admin")


class ContactDialogTest(_DBTestCase):
    def test_save_requires_name_or_phone(self):
        from app.ui.dialogs.contact_dialog import ContactDialog
        from unittest.mock import patch
        dialog = ContactDialog("Nouveau client", with_debt=True)
        with patch("app.ui.dialogs.contact_dialog.warn") as warn_box:
            dialog._save()
            warn_box.assert_called_once()
        self.assertIsNone(dialog.data)

    def test_save_with_phone_only_builds_default_name(self):
        from app.ui.dialogs.contact_dialog import ContactDialog
        dialog = ContactDialog("Nouveau client")
        dialog.phone.setText("70112233")
        dialog._save()
        self.assertEqual(dialog.data["name"], "Client 70112233")


class ClientPurchasesDialogTest(_DBTestCase):
    def test_builds_with_header_and_loads_summary(self):
        from app.controllers.client_controller import ClientController
        from app.ui.dialogs.client_purchases_dialog import ClientPurchasesDialog
        client = ClientController.create({"name": "Awa Konaté", "phone": "70000000"})
        dialog = ClientPurchasesDialog(client.id, client.name)
        self.assertIn("Awa Konaté", dialog.windowTitle())
        self.assertTrue(dialog.summary.text())


if __name__ == "__main__":
    unittest.main()
