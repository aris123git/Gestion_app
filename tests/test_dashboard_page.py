import os
import tempfile
import unittest

os.environ.setdefault("GESTION_DATA_DIR", tempfile.mkdtemp())
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"


class DashboardPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from app.database.connection import init_database
        from app.database.seed import seed_all
        init_database()
        seed_all()

    def setUp(self):
        # Le profil produit est un fichier local partagé entre tests : on force
        # explicitement "gestion_app" (non-Maquis) via la variable d'environnement,
        # qui prime sur le fichier, pour ne pas dépendre de l'ordre d'exécution.
        os.environ["NEXAGES_PRODUCT"] = "gestion_app"

    def tearDown(self):
        os.environ.pop("NEXAGES_PRODUCT", None)

    def _state(self):
        from app.ui.state import AppState
        st = AppState()
        st.can = lambda _p: True
        return st

    def test_hero_cards_chart_and_stock_health(self):
        from app.controllers.product_controller import ProductController as P
        from app.controllers.sale_controller import CartLine, PaymentLine, SaleController as SC
        from app.ui.pages.dashboard_page import DashboardPage

        p = P.create({"name": "Riz tableau de bord", "sale_price": 1000, "purchase_price": 600, "quantity": 20, "min_stock": 5})
        SC.create_sale([CartLine(p.id, p.name, 1000, 2)], [PaymentLine("Espèces", 2000)], amount_received=2000)
        out = P.create({"name": "Produit en rupture", "sale_price": 500, "purchase_price": 300, "quantity": 0, "min_stock": 3})

        page = DashboardPage(self._state())
        page.refresh()

        self.assertIn("2 000", page.card_revenue_today.value_label.text().replace(" ", " "))
        self.assertEqual(page.card_sales.value_label.text(), "1")
        # Le graphique CA/bénéfice doit contenir 14 points sur chacune des deux séries.
        self.assertEqual(len(page._chart.labels), 14)
        self.assertEqual(len(page._chart.series), 2)
        self.assertEqual(len(page._chart.series[0][2]), 14)
        # La carte de santé du stock reflète bien la rupture créée.
        self.assertEqual(page._stock_health._out[1].text(), "1")
        self.assertGreaterEqual(int(page._stock_health._total[1].text()), 2)
        # Les tables restent peuplées.
        self.assertGreaterEqual(page.top_table.rowCount(), 1)
        self.assertGreaterEqual(page.alert_table.rowCount(), 1)

    def test_alert_table_urgency_pill_colors(self):
        from app.ui.pages.dashboard_page import _urgency_colors
        danger_bg, _ = _urgency_colors(2)
        warning_bg, _ = _urgency_colors(6)
        ok_bg, _ = _urgency_colors(None)
        self.assertEqual(danger_bg, "#fee2e2")
        self.assertEqual(warning_bg, "#fef3c7")
        self.assertEqual(ok_bg, "#f1f5f9")

    def test_insights_chips_and_permissions(self):
        from app.ui.pages.dashboard_page import DashboardPage
        from app.ui.state import AppState

        st = AppState()
        st.can = lambda _p: False  # pas de VIEW_PROFITS ni MANAGE_CLIENT_DEBTS
        page = DashboardPage(st)
        page.refresh()
        # isHidden() ne dépend pas de l'affichage réel de la fenêtre (contrairement à
        # isVisible()), ce qui est nécessaire pour un test hors écran (offscreen).
        self.assertTrue(page._chart_card.isHidden())
        self.assertTrue(page.card_debt.isHidden())

        st2 = self._state()
        page2 = DashboardPage(st2)
        page2.refresh()
        self.assertFalse(page2._chart_card.isHidden())
        self.assertGreater(page2._insights_grid.count(), 0)

    def test_daily_trend_service_returns_expected_shape(self):
        from app.services.dashboard_service import DashboardService
        trend = DashboardService.daily_trend(days=7)
        self.assertEqual(len(trend["labels"]), 7)
        self.assertEqual(len(trend["revenue"]), 7)
        self.assertEqual(len(trend["net_profit"]), 7)


if __name__ == "__main__":
    unittest.main()
