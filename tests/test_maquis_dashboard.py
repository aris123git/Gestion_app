"""Tests tableau de bord Maquis (commandes)."""

import unittest

from app.database.connection import init_database
from app.database.seed import seed_all
from app.services import order_service, product_profile
from app.services.maquis_dashboard_service import today_stats


class MaquisDashboardTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        product_profile.set_product(product_profile.PRODUCT_MAQUIS)

    def test_today_stats_empty_ok(self) -> None:
        stats = today_stats()
        self.assertGreaterEqual(stats.orders_count, 0)
        self.assertGreaterEqual(stats.open_orders, 0)

    def test_counts_open_order(self) -> None:
        from app.services import table_service

        table_service.TableService.ensure_defaults()
        free = next(t for t in table_service.TableService.list() if t.status == "libre")
        order_service.OrderService.open_on_table(free.id)
        stats = today_stats()
        self.assertGreaterEqual(stats.orders_count, 1)
        self.assertGreaterEqual(stats.open_orders, 1)


if __name__ == "__main__":
    unittest.main()
