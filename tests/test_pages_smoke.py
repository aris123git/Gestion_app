"""Test de fumée : chaque page s'ouvre et se rafraîchit sans erreur (administrateur)."""
import importlib, inspect, os, pkgutil, shutil, tempfile, unittest

_D = tempfile.mkdtemp(prefix="gestion_smoke_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402


_KEEP: list = []  # jamais vidé : détruire des pages Qt au ramasse-miettes fait planter le processus


class PagesSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        init_database(); seed_all()
        from app.ui.state import AppState
        cls.state = AppState()
        cls.state.auth.login("admin", "admin")
        cls.keep = _KEEP

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

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



class EnterpriseVisibilityTests(unittest.TestCase):
    def test_bon_settings_only_for_enterprise(self):
        from app.ui.pages.settings_page import SettingsPage
        from app.ui.state import AppState
        app = QApplication.instance() or QApplication([])
        init_database(); seed_all()
        state = AppState(); state.auth.login("admin", "admin")
        page = SettingsPage(state)
        _KEEP.append(page)
        page.show()
        page.shop_type.setCurrentText("Boutique")
        self.assertTrue(page.bon_legal.isHidden())
        self.assertFalse(page.bl_enabled.isHidden())  # le bon de livraison reste pour tous
        page.shop_type.setCurrentText("Entreprise")
        self.assertFalse(page.bon_legal.isHidden())
        self.assertFalse(page.bl_enabled.isHidden())


class BonTabsTests(unittest.TestCase):
    def test_tabs_follow_shop_type_and_settings_persist(self):
        from app.services import settings_service
        from app.ui.pages.settings_page import SettingsPage
        from app.ui.state import AppState
        app = QApplication.instance() or QApplication([])
        init_database(); seed_all()
        state = AppState(); state.auth.login("admin", "admin")
        page = SettingsPage(state)
        _KEEP.append(page)
        page.show()
        tabs = page._tabs
        def visible(tab): return tabs.isTabVisible(tabs.indexOf(tab))
        page.shop_type.setCurrentText("Boutique")
        self.assertFalse(visible(page._tab_bon)); self.assertFalse(visible(page._tab_bl))
        self.assertFalse(page.bl_enabled.isHidden())                      # bon de livraison reste dans Facture
        page.shop_type.setCurrentText("Entreprise")
        self.assertTrue(visible(page._tab_bon)); self.assertTrue(visible(page._tab_bl))
        self.assertTrue(hasattr(page._tab_bon, "verticalScrollBar"))      # onglet défilant
        # champ partagé synchronisé entre onglets
        page._mirrors_bl[1].setText("BF-RCCM-1")
        self.assertEqual(page.shop_rccm.text(), "BF-RCCM-1")
        self.assertEqual(page._mirrors_bon[1].text(), "BF-RCCM-1")
        page.bon_style.setCurrentIndex(page.bon_style.findData("bandeau_vert"))
        page._save_appearance(silent=True)
        self.assertEqual(settings_service.get_setting("bon_style", ""), "bandeau_vert")
        page.refresh()
        self.assertEqual(page.bon_style.currentData(), "bandeau_vert")
        page.pickup_tax_type.setCurrentText("BIC")
        page.shop_type.setCurrentText("Boutique")
        self.assertFalse(visible(page._tab_bon))
        self.assertTrue(page.bon_legal.isHidden())
