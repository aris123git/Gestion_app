"""Commandes Maquis : saisie tactile, encaissement et absence d'impression."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_DATA_DIR = tempfile.mkdtemp(prefix="maquis_orders_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ["NEXAGES_PRODUCT"] = "maquis_caisse"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.database.connection import init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.open_order import STATUS_OPEN  # noqa: E402
from app.services import order_service, table_service  # noqa: E402
from app.ui.pages.orders_page import OrdersPage  # noqa: E402


class MaquisOrderServiceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    def setUp(self) -> None:
        table_service.TableService.ensure_defaults()
        table = next(
            table
            for table in table_service.TableService.list()
            if table.status == "libre"
        )
        self.order = order_service.OrderService.open_on_table(table.id)

    def tearDown(self) -> None:
        current = order_service.OrderService.get(self.order.id)
        if current and current.status == STATUS_OPEN:
            order_service.OrderService.cancel(current.id)

    def test_add_merge_change_and_remove_items(self) -> None:
        order_service.OrderService.add_item(
            self.order.id,
            product_id=None,
            product_name="Alloco",
            quantity=1,
            unit_price=1500,
        )
        merged = order_service.OrderService.add_item(
            self.order.id,
            product_id=None,
            product_name="Alloco",
            quantity=2,
            unit_price=1500,
        )
        self.assertEqual(len(merged.items), 1)
        self.assertEqual(float(merged.items[0].quantity), 3)
        self.assertEqual(float(merged.total), 4500)

        changed = order_service.OrderService.set_item_quantity(
            self.order.id, merged.items[0].id, 2
        )
        self.assertEqual(float(changed.total), 3000)

        empty = order_service.OrderService.remove_item(
            self.order.id, changed.items[0].id
        )
        self.assertEqual(empty.items, [])
        self.assertEqual(float(empty.total), 0)

    def test_each_new_product_is_included_in_total_immediately(self) -> None:
        first = order_service.OrderService.add_item(
            self.order.id,
            product_id=None,
            product_name="Poisson braisé",
            quantity=1,
            unit_price=5000,
        )
        self.assertEqual(float(first.total), 5000)
        second = order_service.OrderService.add_item(
            self.order.id,
            product_id=None,
            product_name="Bière locale",
            quantity=1,
            unit_price=1000,
        )
        self.assertEqual(float(second.total), 6000)

    def test_empty_order_cannot_be_marked_paid(self) -> None:
        with self.assertRaisesRegex(ValueError, "commande vide"):
            order_service.OrderService.mark_paid(self.order.id)


class OrdersPagePaymentTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_mark_paid_records_sale_without_opening_ticket_dialog(self) -> None:
        state = SimpleNamespace(
            current_user=SimpleNamespace(role="admin"),
            user_id=1,
            can=lambda _permission: True,
            notify_data_changed=MagicMock(),
        )
        line = SimpleNamespace(
            product_id=None,
            product_name="Poisson braisé",
            quantity=1,
            unit_price=5000,
            line_total=5000,
        )
        order = SimpleNamespace(
            id=42,
            public_id="CMD-TEST",
            table=None,
            customer_name="",
            note="",
            status=STATUS_OPEN,
            total=5000,
            items=[line],
        )
        payment = SimpleNamespace(
            exec=lambda: True,
            use_credit=False,
            result_payments=[],
            amount_received=5000,
            result_client_id=None,
            credit_due_date=None,
        )
        with (
            patch.object(order_service.OrderService, "list_open", return_value=[order]),
            patch.object(order_service.OrderService, "get", return_value=order),
            patch.object(order_service.OrderService, "mark_paid") as mark_paid,
            patch("app.ui.pages.orders_page.PaymentDialog", return_value=payment),
            patch("app.ui.pages.orders_page.SaleController.create_sale") as create_sale,
            patch("app.ui.pages.orders_page.info"),
            patch("app.ui.dialogs.ticket_dialog.TicketDialog") as ticket_dialog,
        ):
            page = OrdersPage(state)
            page.table.selectRow(0)
            page._pay()

        create_sale.assert_called_once()
        mark_paid.assert_called_once_with(42)
        ticket_dialog.assert_not_called()

if __name__ == "__main__":
    unittest.main()
