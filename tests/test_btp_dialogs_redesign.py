"""BTP (chantiers) : nouvel habillage visuel (bandeaux) des fenêtres pop-up —
vérifie que la logique de ces dialogues reste intacte."""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class _DBTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_btp_dialogs_")
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


class ChantierDialogHeaderTest(_DBTestCase):
    def test_header_banner_shows_name_and_status_and_tabs_intact(self):
        from app.services import chantier_service as cs
        from app.ui.dialogs.chantier_dialog import ChantierDialog
        from app.ui.state import AppState

        cid = cs.create("Villa Redesign", client_label="Client R", amount=1_000_000, status="en_cours")
        state = AppState()
        state.auth.login("admin", "admin")
        dialog = ChantierDialog(state, cid)
        self.assertEqual(dialog.title.parent().objectName(), "DialogHeaderBanner")
        self.assertIn("Villa Redesign", dialog.title.text())
        self.assertEqual(dialog.tabs.count(), 8)


class OrderDialogHeaderTest(_DBTestCase):
    def test_header_banner_present_and_row_still_works(self):
        from app.ui.dialogs.order_dialog import OrderDialog
        from app.ui.state import AppState

        state = AppState()
        state.auth.login("admin", "admin")
        dialog = OrderDialog(state, None, "Issa", "AA 11")
        self.assertEqual((dialog.driver.currentText(), dialog.truck.currentText()), ("Issa", "AA 11"))
        from PySide6.QtWidgets import QFrame
        headers = [f for f in dialog.findChildren(QFrame) if f.objectName() == "DialogHeaderBanner"]
        self.assertEqual(len(headers), 1)


class SendDocumentDialogHeaderTest(_DBTestCase):
    def test_header_banner_and_send_still_work(self):
        from pathlib import Path
        from unittest import mock
        from app.ui.dialogs.send_document_dialog import SendDocumentDialog
        from PySide6.QtWidgets import QFrame

        pdf = Path(self._dir) / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        opened = []
        with mock.patch("app.ui.dialogs.send_document_dialog.QDesktopServices.openUrl", lambda url: opened.append(url.toString())), \
                mock.patch("app.ui.dialogs.send_document_dialog.info", lambda *a, **k: None), \
                mock.patch("app.ui.dialogs.send_document_dialog.warn", lambda *a, **k: None):
            dialog = SendDocumentDialog(None, pdf, "70112233", "client@example.com", "Objet", "Bonjour")
            headers = [f for f in dialog.findChildren(QFrame) if f.objectName() == "DialogHeaderBanner"]
            self.assertEqual(len(headers), 1)
            self.assertTrue(dialog.send_whatsapp())
            self.assertTrue(opened[0].startswith("https://wa.me/"))


if __name__ == "__main__":
    unittest.main()
