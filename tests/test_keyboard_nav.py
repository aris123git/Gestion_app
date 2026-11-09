import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.ui import keyboard


class KeyboardNavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        keyboard.install(cls.app)

    def test_enter_moves_to_next_field_then_submits(self):
        dlg = QDialog()
        lay = QVBoxLayout(dlg)
        a, b = QLineEdit(), QLineEdit()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(dlg.accept)
        for w in (a, b, bb):
            lay.addWidget(w)
        dlg.show(); a.setFocus()
        QTest.keyClick(a, Qt.Key.Key_Return)
        self.assertIs(dlg.focusWidget(), b)
        QTest.keyClick(b, Qt.Key.Key_Return)  # dernier champ : valide comme avant
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)

    def test_enter_presses_focused_button(self):
        w = QDialog(); lay = QVBoxLayout(w)
        btn = QPushButton("Go"); hit = []
        btn.clicked.connect(lambda: hit.append(1)); lay.addWidget(btn)
        w.show(); btn.setFocus()
        QTest.keyClick(btn, Qt.Key.Key_Return)
        self.assertEqual(hit, [1])

    def test_enter_opens_table_row(self):
        t = QTableWidget(2, 1); opened = []
        t.setItem(0, 0, QTableWidgetItem("x")); t.setItem(1, 0, QTableWidgetItem("y"))
        t.cellDoubleClicked.connect(lambda r, c: opened.append(r))
        t.show(); t.setFocus(); t.setCurrentCell(1, 0)
        QTest.keyClick(t, Qt.Key.Key_Return)
        self.assertEqual(opened, [1])

    def test_ctrl_number_shortcuts_on_main_window(self):
        import shutil, tempfile
        d = tempfile.mkdtemp(prefix="gestion_kb_")
        os.environ["GESTION_DATA_DIR"] = d
        os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
        os.environ.pop("NEXAGES_PRODUCT", None)
        from app.database.connection import engine, init_database
        from app.database.seed import seed_all
        engine.dispose(); init_database(); seed_all()
        from app.ui.main_window import MainWindow
        from app.ui.state import AppState
        state = AppState(); state.auth.login("admin", "admin")
        win = MainWindow(state)
        self.assertGreaterEqual(len(win._nav_shortcuts), 2)
        win._nav_shortcuts[1].activated.emit()
        engine.dispose(); shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
