import os, tempfile, unittest
os.environ.setdefault("GESTION_DATA_DIR", tempfile.mkdtemp())
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"


class DeviceLoginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from app.database.connection import init_database
        from app.database.seed import seed_all
        init_database()
        seed_all()

    def setUp(self):
        from app.services import device_login
        device_login.clear_device_login()
        device_login._login_failures = 0
        device_login._blocked_until = 0.0

    def test_set_verify_and_login(self):
        from app.services import device_login
        from app.services.auth_service import AuthService
        admin = AuthService.list_users()[0]
        self.assertIsNone(device_login.get_device_login())
        device_login.set_device_login(admin.id, admin.username, "1234")
        info = device_login.get_device_login()
        self.assertEqual(info["username"], admin.username)
        self.assertFalse(device_login.verify_code("wrong"))
        self.assertTrue(device_login.verify_code("1234"))
        auth = AuthService()
        user = auth.login_device(admin.id)
        self.assertEqual(user.id, admin.id)

    def test_short_code_rejected(self):
        from app.services import device_login
        with self.assertRaises(ValueError):
            device_login.set_device_login(1, "admin", "ab")

    def test_lockout_after_failures(self):
        from app.services import device_login
        device_login.set_device_login(1, "admin", "1234")
        for _ in range(5):
            self.assertFalse(device_login.verify_code("wrong"))
        self.assertFalse(device_login.verify_code("1234"))  # bloqué même avec le bon code
        self.assertGreater(device_login.seconds_blocked(), 0)

    def test_clear(self):
        from app.services import device_login
        device_login.set_device_login(1, "admin", "1234")
        device_login.clear_device_login()
        self.assertIsNone(device_login.get_device_login())

    def test_disabled_account_cannot_login_device(self):
        from app.services.auth_service import AuthService
        a = AuthService()
        a.create_user("tmpuser", "secret12", "Tmp", "Caissier")
        u = next(x for x in AuthService.list_users() if x.username == "tmpuser")
        AuthService.update_user(u.id, is_active=False)
        self.assertIsNone(a.login_device(u.id))


if __name__ == "__main__":
    unittest.main()


class QuickLoginDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from app.database.connection import init_database
        from app.database.seed import seed_all
        init_database()
        seed_all()

    def setUp(self):
        from app.services import device_login
        device_login.clear_device_login()
        device_login._login_failures = 0
        device_login._blocked_until = 0.0

    def test_unlock_flow(self):
        from app.services import device_login
        from app.services.auth_service import AuthService
        from app.ui.quick_login_dialog import QuickLoginDialog
        from app.ui.state import AppState
        admin = AuthService.list_users()[0]
        device_login.set_device_login(admin.id, admin.username, "1234")
        state = AppState()
        dlg = QuickLoginDialog(state, device_login.get_device_login())
        dlg.code.setText("1234")
        dlg._unlock()
        self.assertEqual(state.auth.current_user.id, admin.id)

    def test_switch_to_password(self):
        from app.services import device_login
        from app.services.auth_service import AuthService
        from app.ui.quick_login_dialog import QuickLoginDialog
        from app.ui.state import AppState
        admin = AuthService.list_users()[0]
        device_login.set_device_login(admin.id, admin.username, "1234")
        dlg = QuickLoginDialog(AppState(), device_login.get_device_login())
        dlg._switch_to_password()
        self.assertTrue(dlg.use_password)
