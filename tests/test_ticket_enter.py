"""Entrée dans la fenêtre d'impression : imprimer, puis fermer."""
import os, shutil, tempfile, unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest import mock

_D = tempfile.mkdtemp(prefix="gestion_enter_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def test_enter_prints_then_closes(self):
        from app.ui.dialogs import ticket_dialog as td
        sale = NS(ticket_number="T1", date=datetime.now(), client_id=None, client_name="", client_phone="", items=[], payments=[], subtotal=0, discount=0, total=0, amount_received=0, change_due=0, cashier_name="")
        res = NS(printed=True, message="ok", file_path="x")
        with mock.patch.object(td.thermal_printer, "print_ticket", return_value=res) as pt:
            d = td.TicketDialog(sale, None, auto_print=False)
            d.show()
            key = lambda: QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
            d.keyPressEvent(key())
            self.assertEqual(pt.call_count, 1)
            self.assertTrue(d._printed)
            self.assertTrue(d.isVisible())
            d.keyPressEvent(key())
            self.assertFalse(d.isVisible())


if __name__ == "__main__":
    unittest.main()
