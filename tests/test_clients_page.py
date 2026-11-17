import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GESTION_DATA_DIR"] = tempfile.mkdtemp()


class ClientsPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from app.database.connection import init_database
        from app.database.seed import seed_all
        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()

    def test_filters_detail_and_single_whatsapp(self):
        from app.controllers.client_controller import ClientController as CC
        from app.ui.dialogs import client_message_dialog as dm
        from app.ui.pages import clients_page as mod
        from app.ui.state import AppState

        a = CC.create({"name": "Awa Test", "phone": "+22670112233"}).id
        CC.create({"name": "Sans dette", "phone": ""})
        CC.add_debt(a, 85000, note="credit", due_date=date.today() - timedelta(days=9))
        st = AppState()
        st.can = lambda _p: True
        page = mod.ClientsPage(st)
        page.refresh()
        page._set_filter("overdue")
        self.assertEqual(page.table.rowCount(), 1)
        page.table.setCurrentCell(0, 0)
        self.assertIn("9", page.d_info.text())
        # WhatsApp à un seul client : modèle « rappel de dette » prérempli, lien avec le bon numéro
        dlg = dm.ClientMessageDialog("Awa Test", "+22670112233", 85000)
        self.assertIn("85", dlg.text.toPlainText())
        with mock.patch.object(dm.QDesktopServices, "openUrl") as op:
            dlg._send()
            self.assertIn("wa.me/22670112233", op.call_args[0][0].toString())
        # sans numéro : message d'avertissement, rien d'ouvert
        dlg2 = dm.ClientMessageDialog("Sans dette", "", 0)
        dlg2.text.setPlainText("Bonjour")
        with mock.patch.object(dm.QDesktopServices, "openUrl") as op, mock.patch.object(dm, "warn") as w:
            dlg2._send()
            self.assertTrue(w.called)
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
