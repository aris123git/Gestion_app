"""Tests des contrôles d'intégrité argent (lot A+)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_money_integrity_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.category_controller import CategoryController  # noqa: E402
from app.controllers.expense_controller import ExpenseController  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.report_controller import ReportController  # noqa: E402
from app.controllers.sale_controller import (  # noqa: E402
    CartLine,
    PaymentLine,
    SaleController,
)
from app.controllers.stock_controller import StockController  # noqa: E402
from app.database.connection import engine, init_database, session_scope  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.sale import Sale  # noqa: E402
from app.services import cash_controls, permissions as perms  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.cash_session_service import CashSessionService  # noqa: E402


class MoneyIntegrityTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cash_controls.set_limits(10, 5_000, free_amount=1_000, variance_threshold=200)
        cls.admin = next(
            u for u in AuthService.list_users() if u.role == perms.ROLE_ADMIN
        )
        cls.cashier = AuthService.create_user(
            username="caissier_mi",
            password="caissier1",
            full_name="Caissier MI",
            role=perms.ROLE_CASHIER,
        )
        cats = CategoryController.list()
        cls.product = ProductController.create(
            {
                "name": "Produit MI",
                "sale_price": 500,
                "purchase_price": 200,
                "quantity": 40,
                "category_id": cats[0].id if cats else None,
                "free_amount_sale": True,
            }
        )

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_identify_admin_by_password(self) -> None:
        ident = AuthService.identify_admin_by_password("admin")
        self.assertIsNotNone(ident)
        self.assertEqual(ident[1], "admin")
        self.assertIsNone(AuthService.identify_admin_by_password("wrong"))

    def test_variance_requires_note(self) -> None:
        session = CashSessionService.open_session(self.cashier.id, 1_000)
        with self.assertRaises(ValueError) as ctx:
            CashSessionService.close_session(
                session.id, counted=100, user_id=self.cashier.id
            )
        self.assertIn("note", str(ctx.exception).lower())
        closed = CashSessionService.close_session(
            session.id,
            counted=100,
            note="manque fond tiroir",
            user_id=self.cashier.id,
        )
        self.assertAlmostEqual(float(closed.variance), -900.0, places=2)

    def test_expense_requires_permission(self) -> None:
        with self.assertRaises(ValueError):
            ExpenseController.create({"category": "X", "label": "t", "amount": 10})
        expense = ExpenseController.create(
            {"category": "X", "label": "ok", "amount": 10},
            user_id=self.admin.id,
        )
        self.assertTrue(expense.id)

    def test_stock_cashier_blocked(self) -> None:
        with self.assertRaises(ValueError):
            StockController.stock_out(
                self.product.id, 1, reason="perte", user_id=self.cashier.id
            )
        with self.assertRaises(ValueError):
            StockController.set_inventory(
                self.product.id, 1, user_id=self.cashier.id
            )

    def test_free_amount_cashier_cap(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            SaleController.create_sale(
                [
                    CartLine(
                        self.product.id,
                        self.product.name,
                        500,
                        4,
                        free_amount=True,
                        amount=2_000,
                    )
                ],
                [PaymentLine("Espèces", 2_000)],
                amount_received=2_000,
                user_id=self.cashier.id,
            )
        self.assertIn("Montant libre", str(ctx.exception))

    def test_cancel_age_window(self) -> None:
        result = SaleController.create_sale(
            [CartLine(self.product.id, self.product.name, 500, 1)],
            [PaymentLine("Espèces", 500)],
            amount_received=500,
            user_id=self.cashier.id,
        )
        with session_scope() as session:
            sale = session.get(Sale, result.sale_id)
            sale.date = datetime.now() - timedelta(hours=30)
        with self.assertRaises(ValueError):
            SaleController.cancel_sale(
                result.sale_id,
                reason="annulation pour test motif long",
                user_id=self.cashier.id,
                allow_old_sales=False,
            )
        SaleController.cancel_sale(
            result.sale_id,
            reason="annulation pour test motif long",
            user_id=self.admin.id,
            allow_old_sales=True,
        )

    def test_pending_owner_scoped(self) -> None:
        other = AuthService.create_user(
            username="autre_mi",
            password="autre1",
            full_name="Autre",
            role=perms.ROLE_CASHIER,
        )
        held = SaleController.hold_sale(
            [CartLine(self.product.id, self.product.name, 500, 1)],
            user_id=self.cashier.id,
        )
        mine = SaleController.list_pending(user_id=self.cashier.id)
        theirs = SaleController.list_pending(user_id=other.id)
        self.assertTrue(any(s.id == held.id for s in mine))
        self.assertFalse(any(s.id == held.id for s in theirs))
        with self.assertRaises(ValueError):
            SaleController.claim_pending(held.id, user_id=other.id, allow_any=False)

    def test_z_report_by_cashier(self) -> None:
        report = ReportController.z_report(date.today(), user_id=self.cashier.id)
        self.assertEqual(report["user_id"], self.cashier.id)
        self.assertEqual(report["expenses"], 0.0)
        store = ReportController.z_report(date.today())
        self.assertIn("by_cashier", store)

    def test_manager_has_view_audit(self) -> None:
        self.assertIn(perms.VIEW_AUDIT, perms.permissions_for(perms.ROLE_MANAGER))
        self.assertNotIn(
            perms.VIEW_AUDIT, perms.permissions_for(perms.ROLE_CASHIER)
        )


if __name__ == "__main__":
    unittest.main()
