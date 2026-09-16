"""Commandes de table Maquis Caisse : saisie, réservations, encaissement."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="maquis_orders_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.client_controller import ClientController  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import PaymentLine, SaleController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.dining_table import STATUS_FREE, STATUS_OCCUPIED  # noqa: E402
from app.printers.order_receipt import (  # noqa: E402
    order_as_sale,
    render_order_bill_text,
)
from app.services.order_service import OrderService  # noqa: E402
from app.services.table_service import TableService  # noqa: E402


class MaquisOrderTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    # --- Utilitaires -------------------------------------------------------
    def _beer(self, stock: float = 24.0, name: str = "Bière test"):
        return ProductController.create(
            {
                "name": name,
                "barcode": "",
                "reference": "",
                "purchase_price": 600,
                "sale_price": 1_000,
                "min_price": 0,
                "quantity": stock,
                "min_stock": 2,
                "is_active": True,
            }
        )

    def _fish(self, stock: float = 5.0):
        """Montant libre : 1 carton = 10 kg à 10 000 F, vente 1 500 F/kg."""
        return ProductController.create(
            {
                "name": "Poisson braisé test",
                "barcode": "",
                "reference": "",
                "purchase_price": 10_000,
                "sale_price": 1_500,
                "min_price": 0,
                "pack_content": 10,
                "quantity": stock,
                "min_stock": 1,
                "free_amount_sale": True,
                "is_active": True,
            }
        )

    def _free_table(self):
        TableService.ensure_defaults()
        tables = TableService.list()
        free = [tb for tb in tables if tb.status == STATUS_FREE]
        if not free:
            return TableService.create(number=str(len(tables) + 1), capacity=4)
        return free[0]

    def _open_order(self):
        table = self._free_table()
        order = OrderService.open_on_table(table.id)
        return table, order

    # --- Saisie des articles ----------------------------------------------
    def test_add_merge_quantity_and_remove(self) -> None:
        product = self._beer()
        _table, order = self._open_order()
        OrderService.add_item(
            order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            unit_price=1_000,
            purchase_price=600,
        )
        order = OrderService.add_item(
            order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            unit_price=1_000,
            purchase_price=600,
        )
        self.assertEqual(len(order.items), 1, "un second clic cumule la même ligne")
        self.assertEqual(float(order.items[0].quantity), 2)
        self.assertEqual(float(order.total), 2_000)

        item_id = order.items[0].id
        order = OrderService.set_item_quantity(order.id, item_id, 5)
        self.assertEqual(float(order.total), 5_000)

        order = OrderService.set_item_note(order.id, item_id, "Bien fraîche")
        self.assertEqual(order.items[0].note, "Bien fraîche")

        order = OrderService.remove_item(order.id, item_id)
        self.assertEqual(len(order.items), 0)
        self.assertEqual(float(order.total), 0)

    def test_reserved_quantities_follow_open_orders(self) -> None:
        product = self._beer(stock=10, name="Bière réservation")
        _table, order = self._open_order()
        self.assertNotIn(product.id, OrderService.reserved_quantities())
        OrderService.add_item(
            order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=3,
            unit_price=1_000,
        )
        self.assertAlmostEqual(
            OrderService.reserved_quantities().get(product.id, 0.0), 3.0
        )
        # Le stock produit n'est pas touché avant l'encaissement.
        self.assertEqual(float(ProductController.get(product.id).quantity), 10)
        OrderService.cancel(order.id)
        self.assertNotIn(product.id, OrderService.reserved_quantities())

    def test_free_amount_line_uses_pack_content(self) -> None:
        product = self._fish(stock=5)
        _table, order = self._open_order()
        order = OrderService.add_item(
            order.id,
            product_id=product.id,
            product_name="Poisson braisé test — 3 000 FCFA",
            quantity=2.0,  # 3 000 F / 1 500 F/kg
            unit_price=1_500,
            purchase_price=1_000,
            free_amount=True,
            amount=3_000,
        )
        self.assertEqual(float(order.total), 3_000)
        # 2 kg sur un colis de 10 kg = 0,2 unité de stock réservée.
        self.assertAlmostEqual(
            OrderService.reserved_quantities().get(product.id, 0.0), 0.2, places=4
        )
        result = OrderService.checkout(order.id, amount_received=3_000)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(
            float(ProductController.get(product.id).quantity), 4.8, places=4
        )

    # --- Encaissement ------------------------------------------------------
    def test_checkout_creates_sale_and_frees_table(self) -> None:
        product = self._beer(stock=12, name="Bière encaissement")
        table, order = self._open_order()
        OrderService.add_item(
            order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=3,
            unit_price=1_000,
            purchase_price=600,
        )
        self.assertEqual(TableService.get(table.id).status, STATUS_OCCUPIED)

        result = OrderService.checkout(
            order.id,
            payments=[PaymentLine(method="Espèces", amount=3_000)],
            amount_received=5_000,
        )
        self.assertIsNotNone(result)
        self.assertEqual(float(result.total), 3_000)
        self.assertEqual(float(result.change_due), 2_000)

        sale = SaleController.get(result.sale_id)
        self.assertEqual(sale.status, "completed")
        self.assertEqual(len(sale.items), 1)
        self.assertEqual(float(sale.profit), 1_200)  # (1000 − 600) × 3

        # Stock déduit à l'encaissement seulement.
        self.assertEqual(float(ProductController.get(product.id).quantity), 9)
        # Commande soldée, liée à la vente, table libérée.
        closed = OrderService.get(order.id)
        self.assertEqual(closed.status, "payée")
        self.assertEqual(closed.sale_id, result.sale_id)
        self.assertEqual(TableService.get(table.id).status, STATUS_FREE)
        self.assertFalse(
            any(o.id == order.id for o in OrderService.list_open())
        )

    def test_checkout_with_discount_and_credit_creates_debt(self) -> None:
        from app import config as app_config
        from app.services.debt_service import DebtService

        product = self._beer(stock=20, name="Bière dette")
        client = ClientController.create({"name": "Client maquis", "phone": "0700000111"})
        _table, order = self._open_order()
        OrderService.add_item(
            order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=4,
            unit_price=1_000,
            purchase_price=600,
        )
        result = OrderService.checkout(
            order.id,
            payments=[
                PaymentLine(method="Espèces", amount=1_000),
                PaymentLine(method=app_config.PAYMENT_METHOD_CREDIT, amount=2_500),
            ],
            amount_received=1_000,
            discount=500,
            client_id=client.id,
            allow_credit=True,
        )
        self.assertEqual(float(result.total), 3_500)
        debts = DebtService.list_debts(filter_mode="all")
        matching = [d for d in debts if d.sale_id == result.sale_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(float(matching[0].amount_remaining), 2_500)

    def test_checkout_refuses_more_than_stock(self) -> None:
        from app.controllers.sale_controller import InsufficientStockError

        product = self._beer(stock=2, name="Bière rupture")
        _table, order = self._open_order()
        OrderService.add_item(
            order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=2,
            unit_price=1_000,
        )
        # Une vente en caisse vide le stock avant l'encaissement de la table.
        SaleController.create_sale(
            lines=OrderService.cart_lines(order.id),
            payments=[PaymentLine(method="Espèces", amount=2_000)],
            amount_received=2_000,
        )
        with self.assertRaises(InsufficientStockError):
            OrderService.checkout(order.id, amount_received=2_000)
        # La commande reste ouverte : rien n'est perdu.
        self.assertEqual(OrderService.get(order.id).status, "ouverte")
        OrderService.cancel(order.id)

    def test_empty_order_is_closed_without_sale(self) -> None:
        table, order = self._open_order()
        self.assertIsNone(OrderService.checkout(order.id))
        self.assertEqual(OrderService.get(order.id).status, "payée")
        self.assertEqual(TableService.get(table.id).status, STATUS_FREE)

    # --- Tables ------------------------------------------------------------
    def test_transfer_between_tables(self) -> None:
        product = self._beer(stock=6, name="Bière transfert")
        source, order = self._open_order()
        OrderService.add_item(
            order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            unit_price=1_000,
        )
        target = TableService.create(number="T-transfert", name="Terrasse test")
        order = OrderService.transfer_to_table(order.id, target.id)
        self.assertEqual(order.table_id, target.id)
        self.assertEqual(TableService.get(source.id).status, STATUS_FREE)
        self.assertEqual(TableService.get(target.id).status, STATUS_OCCUPIED)
        summary = OrderService.open_summary_by_table()
        self.assertIn(target.id, summary)
        self.assertEqual(summary[target.id]["total"], 1_000)
        OrderService.cancel(order.id)

    # --- Impressions à la demande -----------------------------------------
    def test_bill_text_contains_lines_and_total(self) -> None:
        product = self._beer(stock=6, name="Bière addition")
        _table, order = self._open_order()
        order = OrderService.add_item(
            order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=2,
            unit_price=1_000,
            note="Sans glace",
        )
        sale_like = order_as_sale(order, cashier="admin")
        self.assertEqual(sale_like.ticket_number, order.public_id)
        self.assertIn("Sans glace", sale_like.items[0].product_name)
        text = render_order_bill_text(order, paper="80mm", cashier="admin")
        self.assertIn("Bière addition", text)
        self.assertIn("2 000", text)
        OrderService.cancel(order.id)


if __name__ == "__main__":
    unittest.main()
