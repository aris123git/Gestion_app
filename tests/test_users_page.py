import os, tempfile, unittest
from unittest.mock import patch
os.environ.setdefault("GESTION_DATA_DIR", tempfile.mkdtemp())
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"


class UsersPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from app.database.connection import init_database
        from app.database.seed import seed_all
        init_database()
        seed_all()

    def test_filter_toggle_and_abilities(self):
        from app.services.auth_service import AuthService as A
        from app.ui.pages import users_page as up
        from app.ui.state import AppState
        A.create_user("caissier1", "secret12", "Awa T", "Caissier")
        st = AppState()
        st.can = lambda _p: True
        pg = up.UsersPage(st)
        pg.refresh()
        pg._set_filter("Caissier")
        names = [pg.table.item(r, 0).text() for r in range(pg.table.rowCount())]
        self.assertIn("caissier1", names)
        self.assertNotIn("admin", names)
        pg.table.selectRow(names.index("caissier1"))
        pg._toggle_active()
        pg._set_filter("inactive")
        self.assertEqual([pg.table.item(r, 0).text() for r in range(pg.table.rowCount())], ["caissier1"])
        pg._toggle_active()
        can, cannot = up.role_abilities("Caissier")
        self.assertIn("Vendre et imprimer les tickets", can)
        self.assertIn("Voir les bénéfices", cannot)
        self.assertEqual(up.role_abilities("Administrateur")[1], [])


if __name__ == "__main__":
    unittest.main()
