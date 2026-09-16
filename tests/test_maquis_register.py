"""Tests caisse table Maquis : add/update/remove item, encaissement, dialogue.

Ces tests couvrent la refonte tablette de la caisse Maquis :

* ``OrderService`` accepte l'ajout et la fusion des lignes, la mise à jour
  et la suppression individuelle, ainsi que la mise à jour de l'entête
  (client, note).
* ``DebtPaymentReceiptDialog`` **n'imprime plus automatiquement** à
  l'ouverture (validation métier : « plus besoin d'imprimer quand on marque
  comme payé »).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

_DATA_DIR = tempfile.mkdtemp(prefix="maquis_register_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.database.connection import init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import order_service, table_service  # noqa: E402


class OrderServiceEditingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        table_service.TableService.ensure_defaults()
        cls.p_coca = ProductController.create(
            {"name": "Coca", "sale_price": 500, "purchase_price": 300, "quantity": 100}
        ).id
        cls.p_biere = ProductController.create(
            {"name": "Bière", "sale_price": 700, "purchase_price": 400, "quantity": 100}
        ).id
        cls.p_frites = ProductController.create(
            {"name": "Frites", "sale_price": 1000, "purchase_price": 500, "quantity": 100}
        ).id
        cls.p_poulet = ProductController.create(
            {"name": "Poulet", "sale_price": 2500, "purchase_price": 1500, "quantity": 100}
        ).id

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def _fresh_order(self):
        tables = table_service.TableService.list()
        free = next(t for t in tables if t.status == "libre")
        return order_service.OrderService.open_on_table(free.id)

    def test_add_item_merges_same_product_same_price(self) -> None:
        order = self._fresh_order()
        order = order_service.OrderService.add_item(
            order.id,
            product_id=self.p_coca,
            product_name="Coca",
            quantity=1,
            unit_price=500,
        )
        self.assertEqual(len(order.items), 1)
        self.assertAlmostEqual(float(order.total), 500.0, places=2)

        order = order_service.OrderService.add_item(
            order.id,
            product_id=self.p_coca,
            product_name="Coca",
            quantity=2,
            unit_price=500,
        )
        self.assertEqual(len(order.items), 1)
        self.assertAlmostEqual(float(order.items[0].quantity), 3.0, places=3)
        self.assertAlmostEqual(float(order.total), 1500.0, places=2)

        order_service.OrderService.mark_paid(order.id)

    def test_add_item_does_not_merge_when_price_differs(self) -> None:
        order = self._fresh_order()
        order = order_service.OrderService.add_item(
            order.id,
            product_id=self.p_biere,
            product_name="Bière",
            quantity=1,
            unit_price=700,
        )
        order = order_service.OrderService.add_item(
            order.id,
            product_id=self.p_biere,
            product_name="Bière (happy hour)",
            quantity=1,
            unit_price=500,
        )
        self.assertEqual(len(order.items), 2)
        self.assertAlmostEqual(float(order.total), 1200.0, places=2)
        order_service.OrderService.cancel(order.id)

    def test_update_and_remove_item(self) -> None:
        order = self._fresh_order()
        order = order_service.OrderService.add_item(
            order.id,
            product_id=self.p_frites,
            product_name="Frites",
            quantity=1,
            unit_price=1000,
        )
        item_id = int(order.items[0].id)
        order = order_service.OrderService.update_item_quantity(order.id, item_id, 4)
        self.assertAlmostEqual(float(order.items[0].quantity), 4.0)
        self.assertAlmostEqual(float(order.total), 4000.0)

        order = order_service.OrderService.update_item_quantity(order.id, item_id, 0)
        self.assertEqual(len(order.items), 0)
        self.assertAlmostEqual(float(order.total), 0.0)
        order_service.OrderService.cancel(order.id)

    def test_set_customer_and_note(self) -> None:
        order = self._fresh_order()
        order = order_service.OrderService.set_customer_name(order.id, "Fatou")
        order = order_service.OrderService.set_note(order.id, "Sans oignons")
        self.assertEqual(order.customer_name, "Fatou")
        self.assertEqual(order.note, "Sans oignons")
        order_service.OrderService.cancel(order.id)

    def test_get_returns_detached_order_with_items(self) -> None:
        order = self._fresh_order()
        order_service.OrderService.add_item(
            order.id,
            product_id=self.p_poulet,
            product_name="Poulet",
            quantity=1,
            unit_price=2500,
        )
        loaded = order_service.OrderService.get(order.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.items), 1)
        self.assertEqual(loaded.items[0].product_name, "Poulet")
        order_service.OrderService.mark_paid(order.id)

    def test_add_rejects_invalid_quantity(self) -> None:
        order = self._fresh_order()
        with self.assertRaises(ValueError):
            order_service.OrderService.add_item(
                order.id,
                product_id=self.p_coca,
                product_name="X",
                quantity=0,
                unit_price=100,
            )
        order_service.OrderService.cancel(order.id)


class DebtPaymentReceiptDialogTestCase(unittest.TestCase):
    """La refonte doit garantir que « Payé » n'imprime plus automatiquement."""

    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    def test_opening_dialog_does_not_call_printer(self) -> None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        self.addCleanup(lambda: None)

        with patch(
            "app.ui.dialogs.debt_payment_receipt_dialog.print_debt_payment"
        ) as printer:
            from app.ui.dialogs.debt_payment_receipt_dialog import (
                DebtPaymentReceiptDialog,
            )

            dialog = DebtPaymentReceiptDialog(
                client_name="Amadou",
                amount=1500,
                payment_method="Espèces",
                remaining_after=0,
            )
            self.addCleanup(dialog.deleteLater)
            printer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
