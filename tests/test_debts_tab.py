import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GESTION_DATA_DIR"] = tempfile.mkdtemp()


class DebtsTabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from app.database.connection import init_database
        from app.database.seed import seed_all
        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()

    def test_group_by_client_pay_and_filters(self):
        from app.controllers.client_controller import ClientController as CC
        from app.services.debt_service import DebtService
        from app.ui.pages import debts_page as mod
        from app.ui.pages.clients_page import ClientsPage
        from app.ui.state import AppState

        a = CC.create({"name": "Zed Deux Dettes", "phone": "+22670000005"}).id
        CC.add_debt(a, 30000, note="d1", due_date=date.today() - timedelta(days=5))
        CC.add_debt(a, 20000, note="d2", due_date=date.today() + timedelta(days=5))
        st = AppState()
        st.can = lambda _p: True
        page = ClientsPage(st)
        self.assertIsNotNone(page.debts)
        page.show_unpaid()
        d = page.debts
        names = [g["name"] for g in d._groups]
        self.assertEqual(names.count("Zed Deux Dettes"), 1)          # une seule ligne pour 2 dettes
        d.clients.setCurrentCell(names.index("Zed Deux Dettes"), 0)
        self.assertEqual(d.debts.rowCount(), 2)
        self.assertEqual(d._group()["remaining"], 50000)
        # paiement sur une dette précise (la 2e)
        d.debts.setCurrentCell(1, 0)
        picked = d._selected_debt()

        class _Dlg:
            result_data = {"amount": 20000, "payment_method": "Espèces", "note": ""}
            def __init__(self, *a, **k): pass
            def exec(self): return 1

        with mock.patch.object(mod, "DebtPaymentDialog", _Dlg), mock.patch("app.ui.dialogs.debt_payment_receipt_dialog.DebtPaymentReceiptDialog") as rc:
            rc.return_value.exec.return_value = 0
            d._settle()
        self.assertEqual(float(DebtService.get(picked.id).amount_remaining), 0)
        self.assertEqual(d._group()["remaining"], 30000)
        # filtre « Échues » : la dette en retard seulement
        d._set_filter("overdue")
        g = [g for g in d._groups if g["name"] == "Zed Deux Dettes"][0]
        self.assertEqual(len(g["debts"]), 1)
        # « Payées » : la dette soldée
        d._set_filter("paid")
        g = [g for g in d._groups if g["name"] == "Zed Deux Dettes"][0]
        self.assertEqual(len(g["debts"]), 1)

    def test_overdue_segment_and_invoice_history(self):
        from datetime import datetime
        from app.controllers.client_controller import ClientController as CC
        from app.services import messaging_service as ms
        from app.ui.dialogs.client_purchases_dialog import ClientPurchasesDialog

        late = CC.create({"name": "Retard Seg", "phone": "+22670000007"}).id
        ok = CC.create({"name": "Pas Retard Seg", "phone": "+22670000008"}).id
        CC.add_debt(late, 1000, note="x", due_date=date.today() - timedelta(days=3))
        CC.add_debt(ok, 1000, note="y", due_date=date.today() + timedelta(days=3))
        names = [r.name for r in ms.find_recipients(ms.SEG_OVERDUE, ms.WHATSAPP, respect_gap=False)]
        self.assertIn("Retard Seg", names)
        self.assertNotIn("Pas Retard Seg", names)
        dlg = ClientPurchasesDialog(late, "Retard Seg")
        self.assertTrue(dlg.all_dates.isChecked())
        dlg.all_dates.setChecked(False)          # période choisie : aujourd'hui seulement, aucune vente
        self.assertEqual(dlg.table.rowCount(), 0)


if __name__ == "__main__":
    unittest.main()
