import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent('''
    import sys
    sys.path.insert(0, r"%s")
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from app.database.connection import init_database
    from app.database.seed import seed_all
    init_database(); seed_all()
    from app.services import field_sales_service as fs
    from app.ui.pages.field_sales_page import FieldSalesPage, CloseDialog, OutDialog
    from app.ui.state import AppState
    fs.set_enabled(True)
    fs.save_seller(name="Moussa", phone="+22670000000")
    state = AppState(); state.auth.login("admin", "admin")
    page = FieldSalesPage(state)
    page.refresh()
    assert page.sellers.rowCount() == 1, page.sellers.rowCount()
    assert page.tabs.count() == 4
    assert "WhatsApp" in page.b_wa.text()
    from app.ui.main_window import build_nav_items
    assert any("Tourn" in str(i[0]) for i in build_nav_items())
    fs.set_enabled(False)
    assert not any("Tourn" in str(i[0]) for i in build_nav_items())
    print("OK")
''')


class FieldSalesUITest(unittest.TestCase):
    def test_page_and_nav(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, GESTION_DATA_DIR=d, NEXAPOS_SKIP_ACTIVATION="1", QT_QPA_PLATFORM="offscreen")
            env.pop("NEXAGES_PRODUCT", None)
            r = subprocess.run([sys.executable, "-c", SCRIPT % ROOT], env=env, capture_output=True, text=True, timeout=120)
            self.assertIn("OK", r.stdout, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
