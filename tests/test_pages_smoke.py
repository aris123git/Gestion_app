"""Test de fumée : chaque page s'ouvre et se rafraîchit sans erreur (administrateur)."""
import importlib, inspect, os, pkgutil, shutil, tempfile, unittest

_D = tempfile.mkdtemp(prefix="gestion_smoke_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402


class PagesSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        init_database(); seed_all()
        from app.ui.state import AppState
        cls.state = AppState()
        cls.state.auth.login("admin", "admin")
        cls.keep = []

    @classmethod
    def tearDownClass(cls):
        cls.keep.clear(); engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def test_every_page_opens_and_refreshes(self):
        import app.ui.pages as pages
        count = 0
        for m in pkgutil.iter_modules(pages.__path__):
            mod = importlib.import_module("app.ui.pages." + m.name)
            for name, cls in inspect.getmembers(mod, inspect.isclass):
                if cls.__module__ != mod.__name__ or not issubclass(cls, QWidget) or not name.endswith("Page"):
                    continue
                with self.subTest(page=name):
                    page = cls(self.state)
                    self.keep.append(page)  # évite la destruction prématurée côté Qt
                    if hasattr(page, "refresh"):
                        page.refresh()
                    self.app.processEvents()
                    count += 1
        self.assertGreaterEqual(count, 20)


if __name__ == "__main__":
    unittest.main()
