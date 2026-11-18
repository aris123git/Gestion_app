import os
import tempfile
import unittest
from unittest import mock

os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GESTION_DATA_DIR"] = tempfile.mkdtemp()


class AvoirsTabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from app.database.connection import init_database
        from app.database.seed import seed_all
        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()

    def test_create_partial_use_filters_cancel(self):
        from app.controllers.client_controller import ClientController as CC
        from app.services.avoir_service import AvoirService
        from app.ui.pages import avoirs_page as mod
        from app.ui.pages.clients_page import ClientsPage
        from app.ui.state import AppState

        cid = CC.create({"name": "Avoir Client", "phone": "+22670000011"}).id
        a = AvoirService.create(amount=5000, client_id=cid, customer_name="Avoir Client", reason="retour")
        AvoirService.create(amount=1000, reason="geste")
        st = AppState()
        st.can = lambda _p: True
        page = ClientsPage(st)
        self.assertIsNotNone(page.avoirs)
        av = page.avoirs
        av.refresh()
        ids = [x.id for x in av._rows]
        self.assertIn(a.id, ids)
        av.table.setCurrentCell(ids.index(a.id), 0)

        class _Use:                       # utilisation partielle de 2000
            def __init__(self, rest, parent=None):
                self.amount = mock.Mock(value=lambda: 2000)
                self.note = mock.Mock(text=lambda: "")
            def exec(self): return 1

        with mock.patch.object(mod, "UseAvoirDialog", _Use):
            av._redeem_selected()
        got = AvoirService.get(a.id)
        self.assertEqual(float(got.amount_remaining), 3000)
        self.assertEqual(got.status, "partiellement_utilisé")
        self.assertEqual(len(AvoirService.redemptions(a.id)), 1)
        # annulation, puis filtre « Annulés »
        av.table.setCurrentCell([x.id for x in av._rows].index(a.id), 0)
        with mock.patch.object(mod, "confirm", return_value=True):
            av._cancel_selected()
        av._set_filter("cancelled")
        self.assertIn(a.id, [x.id for x in av._rows])
        av._set_filter("active")
        self.assertNotIn(a.id, [x.id for x in av._rows])


if __name__ == "__main__":
    unittest.main()
