import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class NavStateTest(unittest.TestCase):
    def setUp(self):
        from app.services import nav_state
        nav_state.set_open_groups(set())

    def tearDown(self):
        from app.services import nav_state
        nav_state.set_open_groups(set())

    def test_round_trip(self):
        from app.services import nav_state
        self.assertEqual(nav_state.get_open_groups(), set())
        nav_state.set_open_groups({"Finances", "Administration"})
        self.assertEqual(nav_state.get_open_groups(), {"Finances", "Administration"})
        nav_state.set_open_groups(set())
        self.assertEqual(nav_state.get_open_groups(), set())

    def test_group_reopens_after_restart(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from app.database.connection import init_database
        from app.database.seed import seed_all
        init_database()
        seed_all()
        from app.ui.main_window import MainWindow
        from app.ui.state import AppState
        state = AppState()
        state.auth.login("admin", "admin")
        win1 = MainWindow(state)
        self.assertIn("Finances", win1._groups)
        win1._toggle_group("Finances")
        self.assertTrue(win1._groups["Finances"]["open"])
        win2 = MainWindow(state)
        self.assertTrue(win2._groups["Finances"]["open"])


if __name__ == "__main__":
    unittest.main()
