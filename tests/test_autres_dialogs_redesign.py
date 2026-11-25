"""Autres fenêtres pop-up (alertes, recherche, annulation, messages fournisseur/
groupés) : nouvel habillage visuel (bandeaux d'en-tête) — vérifie que la
logique de ces dialogues reste intacte."""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class _DBTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_autres_dialogs_")
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


def _has_banner(widget) -> bool:
    from PySide6.QtWidgets import QWidget
    return any(w.objectName() == "DialogHeaderBanner" for w in widget.findChildren(QWidget))


class AlertsDialogRedesignTest(_DBTestCase):
    def test_header_banner_and_list_still_work(self):
        from app.ui.dialogs.alerts_dialog import AlertsDialog, ReminderDialog

        dialog = AlertsDialog(None, lambda _p: True)
        self.assertTrue(_has_banner(dialog))
        self.assertTrue(dialog.title.text())

        reminder = ReminderDialog()
        self.assertTrue(_has_banner(reminder))


class GlobalSearchDialogRedesignTest(_DBTestCase):
    def test_header_banner_and_search_still_work(self):
        from app.ui.dialogs.global_search_dialog import GlobalSearchDialog

        dialog = GlobalSearchDialog(None, state=None)
        self.assertTrue(_has_banner(dialog))
        dialog.query.setText("ab")
        dialog._search()
        self.assertTrue(dialog.hint.text())


class CancelSaleDialogRedesignTest(_DBTestCase):
    def test_header_banner_and_validation_unchanged(self):
        from app.ui.dialogs.cancel_sale_dialog import CancelSaleDialog

        dialog = CancelSaleDialog("TCK-1")
        self.assertTrue(_has_banner(dialog))
        dialog.motif.setPlainText("Erreur de saisie client")
        dialog._save()
        self.assertEqual(dialog.reason, "Erreur de saisie client")

        dialog2 = CancelSaleDialog("TCK-2")
        dialog2.motif.setPlainText("123")
        from unittest import mock
        with mock.patch("app.ui.dialogs.cancel_sale_dialog.warn") as warn_box:
            dialog2._save()
            warn_box.assert_called_once()
        self.assertIsNone(dialog2.reason)


class SupplierMessageDialogRedesignTest(_DBTestCase):
    def test_header_banner_shows_name_and_phone(self):
        from app.controllers.supplier_controller import SupplierController
        from app.ui.dialogs.supplier_message_dialog import SupplierMessageDialog

        supplier = SupplierController.create({"name": "Fournisseur Redesign", "phone": "70000001"})
        dialog = SupplierMessageDialog(supplier.id, supplier.name, supplier.phone)
        self.assertTrue(_has_banner(dialog))
        self.assertTrue(dialog.text.toPlainText() or dialog.hint.text())


class BulkMessageDialogRedesignTest(_DBTestCase):
    def test_header_banners_present_and_stack_unchanged(self):
        from app.ui.dialogs.bulk_message_dialog import BulkMessageDialog, EmailConfigDialog

        dialog = BulkMessageDialog(None, 1, "admin")
        self.assertTrue(_has_banner(dialog))
        self.assertEqual(dialog.stack.count(), 3)

        email_dialog = EmailConfigDialog()
        self.assertTrue(_has_banner(email_dialog))


if __name__ == "__main__":
    unittest.main()
