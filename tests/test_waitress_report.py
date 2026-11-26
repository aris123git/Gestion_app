"""Choix du type de boutique « Maquis » distinct de « Restaurant » et
rapport serveuses (ventes/encaissements + commission/pourboire)."""
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class _DBTestCase(unittest.TestCase):
    """Isole la base ET force le mode Maquis (uniquement pour ces tests —
    patch.dict() restaure l'environnement à la fin de chaque test pour ne
    pas affecter les autres fichiers de la suite)."""

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_waitress_report_")
        self._env_patch = mock.patch.dict(
            os.environ, {"GESTION_DATA_DIR": self._dir, "NEXAGES_PRODUCT": "maquis"}
        )
        self._env_patch.start()
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
        self._env_patch.stop()
        shutil.rmtree(self._dir, ignore_errors=True)


class ShopTypeChoiceTest(unittest.TestCase):
    def test_maquis_is_a_standalone_shop_type(self):
        from app.ui.setup_wizard import SHOP_TYPES
        self.assertIn("Maquis", SHOP_TYPES)
        self.assertIn("Restaurant", SHOP_TYPES)
        # Les deux restent des choix distincts (pas fusionnés).
        self.assertNotEqual(SHOP_TYPES.index("Maquis"), SHOP_TYPES.index("Restaurant"))


class WaitressCommissionRateTest(_DBTestCase):
    def test_create_and_update_commission_rate(self):
        from app.services.auth_service import AuthService

        user = AuthService.create_user(
            "fatou", "secret123", "Fatou", "Caissier", is_waitress=True, commission_rate=10
        )
        self.assertTrue(user.is_waitress)
        self.assertEqual(float(user.commission_rate), 10.0)

        AuthService.update_user(user.id, commission_rate=15)
        refreshed = next(u for u in AuthService.list_users() if u.id == user.id)
        self.assertEqual(float(refreshed.commission_rate), 15.0)


class WaitressCommissionReportTest(_DBTestCase):
    def _seed_paid_order(self, waitress_id, waitress_name, total):
        from app.database.connection import session_scope
        from app.models.open_order import STATUS_PAID, OpenOrder

        with session_scope() as session:
            order = OpenOrder(
                public_id="CMD-TEST",
                status=STATUS_PAID,
                waitress_id=waitress_id,
                waitress_name=waitress_name,
                total=total,
                paid_amount=total,
            )
            session.add(order)

    def test_report_computes_commission_from_user_rate(self):
        from app.services.auth_service import AuthService
        from app.services.maquis_dashboard_service import waitress_commission_report

        user = AuthService.create_user(
            "awa", "secret123", "Awa", "Caissier", is_waitress=True, commission_rate=10
        )
        self._seed_paid_order(user.id, user.full_name, 10000)

        start = datetime.now() - timedelta(hours=1)
        end = datetime.now() + timedelta(hours=1)
        rows = waitress_commission_report(start=start, end=end)
        row = next(r for r in rows if r.waitress_id == user.id)
        self.assertEqual(row.ca_collected, 10000)
        self.assertEqual(row.commission_rate, 10.0)
        self.assertEqual(row.commission_amount, 1000.0)

    def test_waitress_without_rate_has_zero_commission(self):
        from app.services.auth_service import AuthService
        from app.services.maquis_dashboard_service import waitress_commission_report

        user = AuthService.create_user("mai", "secret123", "Mai", "Caissier", is_waitress=True)
        self._seed_paid_order(user.id, user.full_name, 5000)

        start = datetime.now() - timedelta(hours=1)
        end = datetime.now() + timedelta(hours=1)
        rows = waitress_commission_report(start=start, end=end)
        row = next(r for r in rows if r.waitress_id == user.id)
        self.assertEqual(row.commission_amount, 0.0)


class WaitressReportPageTest(_DBTestCase):
    def test_page_builds_and_lists_waitresses(self):
        from app.services.auth_service import AuthService
        from app.ui.pages.waitress_report_page import WaitressReportPage
        from app.ui.state import AppState

        user = AuthService.create_user(
            "ina", "secret123", "Ina", "Caissier", is_waitress=True, commission_rate=5
        )
        self._seed_paid_order(user.id, user.full_name, 8000)

        state = AppState()
        state.auth.login("admin", "admin")
        page = WaitressReportPage(state)
        page.refresh()
        self.assertGreaterEqual(page.table.rowCount(), 1)
        self.assertTrue(page.total_label.text())


class UserDialogCommissionFieldTest(_DBTestCase):
    def test_commission_field_toggles_with_waitress_checkbox(self):
        from app.ui.pages.users_page import UserDialog

        dialog = UserDialog()
        if not dialog.waitress.isVisible():
            self.skipTest("Champ serveuse non visible hors mode Maquis")
        self.assertFalse(dialog.commission_rate.isVisible())
        dialog.waitress.setChecked(True)
        self.assertTrue(dialog.commission_rate.isVisible())
        dialog.commission_rate.setValue(12.5)
        dialog.username.setText("sara")
        dialog.password.setText("secret123")
        dialog._save()
        self.assertEqual(dialog.data["commission_rate"], 12.5)
        self.assertTrue(dialog.data["is_waitress"])


if __name__ == "__main__":
    unittest.main()
