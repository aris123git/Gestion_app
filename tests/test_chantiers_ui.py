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
        self.assertEqual(dlg.tabs.count(), 7)
        self.assertIn("1 500 000", dlg.kpi.text().replace(" ", " ").replace("\xa0", " "))     # reste à encaisser
        dlg.exp_amount.setValue(10_000); dlg.exp_label.setText("Clous"); dlg._add_expense()
        self.assertEqual(cs.summary(cid).spent, 310_000)
        dlg.pay_amount.setValue(100_000)
        from unittest import mock
        with mock.patch("app.ui.dialogs.chantier_dialog.confirm", return_value=False):
            dlg._add_payment()
        self.assertEqual(cs.summary(cid).received, 600_000)

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

    def test_menu_only_for_enterprise(self):
        from app.ui import main_window
        shop = settings_service.get_shop_info()
        settings_service.save_shop_info(name=shop.name, address=shop.address, phone=shop.phone, email=shop.email, currency=shop.currency,
                                        shop_type="Boutique", vat_rate=shop.vat_rate, logo_path=shop.logo_path, is_configured=True)
        self.assertNotIn("Chantiers", [i[0] for i in main_window.build_nav_items()])
        settings_service.save_shop_info(name=shop.name, address=shop.address, phone=shop.phone, email=shop.email, currency=shop.currency,
                                        shop_type="Entreprise", vat_rate=shop.vat_rate, logo_path=shop.logo_path, is_configured=True)
        self.assertIn("Chantiers", [i[0] for i in main_window.build_nav_items()])


if __name__ == "__main__":
    unittest.main()
