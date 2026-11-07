"""Écrans Chantiers : liste, fiche à onglets, permissions du chef de chantier, menu réservé au type Entreprise."""
import os, shutil, tempfile, unittest

_D = tempfile.mkdtemp(prefix="gestion_chantiers_ui_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import chantier_service as cs, permissions as perms, settings_service  # noqa: E402
from app.ui.state import AppState  # noqa: E402


class ChantierUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        init_database(); seed_all()
        cls.keep = []

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def _state(self, role=perms.ROLE_ADMIN):
        state = AppState()
        state.auth.login("admin", "admin")
        if role != perms.ROLE_ADMIN:
            state.auth._current_user.role = role if hasattr(state.auth, "_current_user") else role
        self.keep.append(state)
        return state

    def test_page_and_dialog(self):
        from app.ui.dialogs.chantier_dialog import ChantierDialog
        from app.ui.pages.chantiers_page import ChantiersPage
        cid = cs.create("Villa UI", client_label="Client UI", amount=2_000_000, status="en_cours")
        cs.add_payment(cid, amount=500_000, kind="Avance")
        cs.add_expense(cid, category="Matériel", amount=300_000)
        state = self._state()
        page = ChantiersPage(state); self.keep.append(page)
        page.refresh()
        self.assertGreaterEqual(page.table.rowCount(), 1)
        self.assertIn("Villa UI", page.table.item(0, 1).text())
        dlg = ChantierDialog(state, cid); self.keep.append(dlg)
        self.assertEqual(dlg.tabs.count(), 8)
        self.assertIn("1 500 000", dlg.kpi.text().replace(" ", " ").replace("\xa0", " "))     # reste à encaisser
        dlg.exp_amount.setValue(10_000); dlg.exp_label.setText("Clous"); dlg._add_expense()
        self.assertEqual(cs.summary(cid).spent, 310_000)
        dlg.pay_amount.setValue(100_000)
        from unittest import mock
        with mock.patch("app.ui.dialogs.chantier_dialog.confirm", return_value=False):
            dlg._add_payment()
        self.assertEqual(cs.summary(cid).received, 600_000)

    def test_budget_tab_saves_and_alerts(self):
        from app.ui.dialogs.chantier_dialog import ChantierDialog
        cid = cs.create("Budget UI", client_label="C", amount=1_000_000, status="en_cours")
        cs.add_expense(cid, category="Matériel", amount=60_000)
        dlg = ChantierDialog(self._state(), cid); self.keep.append(dlg)
        dlg.budget_spins["Matériel"].setValue(50_000)
        dlg._save_budget()
        self.assertEqual(cs.summary(cid).cost_budget, {"Matériel": 50_000})
        self.assertTrue(any("Budget dépassé" in a for a in cs.summary(cid).alerts))

    def test_rentals_and_labor_pages(self):
        from datetime import datetime, timedelta
        from app.services import labor_service as ls, rental_service as rs
        from app.ui.pages.labor_page import LaborPage
        from app.ui.pages.rentals_page import RentalsPage
        i = rs.save_item(name="Bétonnière UI", quantity=1, rate_day=10_000, deposit=20_000)
        rid = rs.create_rental(client_label="Client Loc", due_date=datetime.now() - timedelta(days=1), start_date=datetime.now() - timedelta(days=3),
                               lines=[rs.LineInput(i, 1)])
        state = self._state()
        page = RentalsPage(state); self.keep.append(page)
        page.refresh()
        self.assertEqual(page.table.rowCount(), 1)
        self.assertIn("EN RETARD", page.table.item(0, 5).text())
        self.assertIn("retard", page.banner.text())
        self.assertEqual(page.park.rowCount(), 1)
        from app.printers import rental_docs
        from tests.pdf_text import pdf_text
        out = os.path.join(_D, "contrat.pdf")
        rental_docs.build_contract(rid, out)
        self.assertIn("Client Loc", pdf_text(out))
        c = cs.create("Chantier Paie", client_label="C", amount=100_000, status="en_cours")
        w = ls.save_worker(name="Ouvrier UI", daily_rate=4000)
        ls.clock_in(w, c, date=datetime(2026, 11, 3))
        lab = LaborPage(state); self.keep.append(lab)
        lab.refresh()
        self.assertEqual(lab.days.rowCount(), 1)
        self.assertEqual(lab.payroll.rowCount(), 1)
        self.assertEqual(lab.workers.rowCount(), 1)

    def test_edit_client_and_invoice(self):
        from unittest import mock
        from PySide6.QtWidgets import QDialog
        from app.ui.dialogs.chantier_dialog import ChantierDialog
        from app.ui.pages import chantiers_page
        cid = cs.create("Commande mobilier", client_label="Ancien", amount=5_000_000, status="en_cours")
        dlg = ChantierDialog(self._state(), cid); self.keep.append(dlg)

        def fake_exec(self_):
            self_.client.setCurrentText("Société Nouvelle")
            self_.name.setText("100 tables, 200 chaises, 50 portes")
            return QDialog.DialogCode.Accepted

        with mock.patch.object(chantiers_page.NewChantierDialog, "exec", fake_exec):
            dlg._edit_info()
        self.assertEqual(cs.summary(cid).name, "100 tables, 200 chaises, 50 portes")
        with mock.patch.object(dlg, "_open_pdf") as opened:
            dlg._pdf_invoice()
        self.assertTrue(str(opened.call_args[0][0]).endswith(".pdf"))

    def test_site_manager_sees_no_finance(self):
        from app.ui.dialogs.chantier_dialog import ChantierDialog
        cid = cs.create("Chantier chef", amount=1_000_000, status="en_cours")
        state = self._state(perms.ROLE_CASHIER)
        self.assertFalse(state.can(perms.VIEW_CHANTIER_FINANCE))
        self.assertTrue(state.can(perms.ADD_CHANTIER_EXPENSES))
        dlg = ChantierDialog(state, cid); self.keep.append(dlg)
        titles = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
        self.assertNotIn("Encaissements", titles); self.assertNotIn("Avenants", titles)
        self.assertNotIn("Marge", dlg.kpi.text())

    def test_menu_only_in_chantiers_product(self):
        from app.services import product_profile
        from app.ui import main_window
        import os
        saved = os.environ.pop("NEXAGES_PRODUCT", None)
        self.addCleanup(lambda: saved is not None and os.environ.__setitem__("NEXAGES_PRODUCT", saved))
        product_profile.set_product(product_profile.PRODUCT_GESTION)
        self.assertNotIn("Chantiers", [i[0] for i in main_window.build_nav_items()])
        product_profile.set_product(product_profile.PRODUCT_CHANTIERS)
        try:
            names = [i[0] for i in main_window.build_nav_items()]
            self.assertEqual(names[0], "Chantiers")
            self.assertNotIn("Caisse", names)
            from app.services import chantiers_nav
            chantiers_nav.set_sales_enabled(True)
            names = [i[0] for i in main_window.build_nav_items()]
            self.assertIn("Caisse", names)
            self.assertIn("Chantiers", names)
            chantiers_nav.set_sales_enabled(False)
            self.assertIn("Main-d'œuvre", names)
            self.assertNotIn("Locations", names)
            chantiers_nav.set_rentals_enabled(True)
            self.assertIn("Locations", [i[0] for i in main_window.build_nav_items()])
            chantiers_nav.set_rentals_enabled(False)
        finally:
            product_profile.set_product(product_profile.PRODUCT_GESTION)


if __name__ == "__main__":
    unittest.main()
