import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class AssistantPageTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_assistant_")
        os.environ["GESTION_DATA_DIR"] = self._dir
        os.environ.pop("NEXAGES_PRODUCT", None)
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

    def test_sections_and_navigation_to_stock(self):
        from app.controllers.product_controller import ProductController
        from app.ui.main_window import MainWindow
        from app.ui.pages.assistant_page import AssistantPage
        from app.ui.state import AppState
        ProductController.create({"name": "Rupture test", "sale_price": 1000, "purchase_price": 600, "quantity": 0, "min_stock": 5})
        state = AppState()
        state.auth.login("admin", "admin")
        win = MainWindow(state)
        from app.i18n import t
        page = win._select_page_by_label(t("nav.assistant"))
        self.assertIsInstance(page, AssistantPage)
        page.refresh()
        self.assertTrue(any(w.isVisible() for w in page.section_cards.values()))
        rows = page.sections["danger"]
        self.assertGreater(rows.count(), 0)
        page._go_to("nav.stock", "À commander")
        stock_page = win._select_page_by_label(t("nav.stock"))
        self.assertIsNotNone(stock_page)
        self.assertEqual(stock_page.tabs.tabText(stock_page.tabs.currentIndex()), t("À commander"))

    def test_empty_state_when_no_recommendation(self):
        from app.ui.pages.assistant_page import AssistantPage
        from app.ui.state import AppState
        from unittest.mock import patch
        state = AppState()
        with patch("app.ui.pages.assistant_page.AssistantService.recommendations", return_value=[]):
            page = AssistantPage(state)
            page.refresh()
        self.assertTrue(page.empty_label.isVisible())
        for card in page.section_cards.values():
            self.assertFalse(card.isVisible())


if __name__ == "__main__":
    unittest.main()
