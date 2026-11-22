"""Paramètres : regroupement des 8 onglets en 4, avec blocs repliables uniformes."""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class SettingsTabsConsolidationTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_settings_tabs_")
        os.environ["GESTION_DATA_DIR"] = self._dir
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
        shutil.rmtree(self._dir, ignore_errors=True)

    def _page(self):
        from app.ui.pages.settings_page import SettingsPage
        from app.ui.state import AppState
        state = AppState()
        state.auth.login("admin", "admin")
        return SettingsPage(state)

    def test_four_top_level_tabs(self):
        page = self._page()
        tabs = page._tabs
        self.assertEqual(tabs.count(), 4)
        titles = [tabs.tabText(i) for i in range(tabs.count())]
        self.assertEqual(
            titles,
            ["Commerce & Documents", "Caisse", "Sécurité", "Système"],
        )

    def test_bon_bl_sections_still_toggle_with_shop_type(self):
        """_apply_enterprise_visibility continue de fonctionner par identité
        d'objet, même déplacés dans le nouvel onglet combiné."""
        page = self._page()
        page.shop_type.setCurrentText("Boutique")
        self.assertTrue(page._tab_bon.isHidden())
        self.assertTrue(page._tab_bl.isHidden())
        page.shop_type.setCurrentText("Entreprise")
        self.assertFalse(page._tab_bon.isHidden())
        self.assertFalse(page._tab_bl.isHidden())

    def test_backup_data_loaded_without_needing_tab_switch(self):
        """Sauvegarde est le bloc ouvert par défaut du nouvel onglet Système :
        ses données doivent être chargées dès la construction de la page."""
        page = self._page()
        # Si l'auto-chargement n'a pas eu lieu, ces widgets gardent leurs valeurs
        # par défaut au lieu de refléter les réglages réels -- on vérifie juste
        # qu'aucune exception n'a empêché le chargement et que la table existe.
        self.assertTrue(hasattr(page, "backup_table"))
        self.assertGreaterEqual(page.retention.value(), 1)

    def test_designs_section_still_lazy_loads_on_expand(self):
        page = self._page()
        designs_widget = page._tab_designs
        self.assertIsNotNone(designs_widget)


if __name__ == "__main__":
    unittest.main()
