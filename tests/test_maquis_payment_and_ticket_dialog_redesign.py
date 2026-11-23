"""Caisse Maquis : paiement (puces de mode) et aperçu ticket — nouvel habillage
visuel, logique de calcul/validation inchangée."""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class MaquisPaymentDialogRedesignTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_maquis_payment_dialog_")
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

    def test_mode_buttons_toggle_active_object_name(self):
        from app.ui.dialogs.maquis_payment_dialog import MaquisPaymentDialog, MODE_MIXED, MODE_CASH
        dialog = MaquisPaymentDialog(5000)
        self.assertEqual(dialog._mode_buttons[MODE_CASH].objectName(), "ChipActive")
        dialog._select_mode(MODE_MIXED)
        self.assertEqual(dialog._mode_buttons[MODE_MIXED].objectName(), "ChipActive")
        self.assertEqual(dialog._mode_buttons[MODE_CASH].objectName(), "Chip")

    def test_cash_confirm_still_produces_breakdown(self):
        from app.ui.dialogs.maquis_payment_dialog import MaquisPaymentDialog
        dialog = MaquisPaymentDialog(5000)
        dialog._amount_tendered = "5000"
        dialog._tendered_explicit = True
        dialog._refresh_ui()
        dialog._confirm()
        self.assertIsNotNone(dialog.result_data)
        self.assertEqual(dialog.result_data.breakdown.change_amount, 0)


class TicketDialogRedesignTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_ticket_dialog_")
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

    def _sale(self):
        from app.controllers.product_controller import ProductController
        from app.controllers.sale_controller import CartLine, PaymentLine, SaleController
        product = ProductController.create({
            "name": "Savon", "sale_price": 500, "purchase_price": 300,
            "quantity": 50, "min_stock": 2,
        })
        result = SaleController.create_sale(
            [CartLine(product.id, "Savon", 500, 2)],
            [PaymentLine("Espèces", 1000)],
            amount_received=1000,
        )
        return SaleController.get(result.sale_id)

    def test_dialog_builds_with_header_banner(self):
        from app.ui.dialogs.ticket_dialog import TicketDialog
        sale = self._sale()
        dialog = TicketDialog(sale, auto_print=False)
        self.assertIn(sale.ticket_number, dialog.windowTitle())
        self.assertTrue(dialog.preview.toPlainText())


if __name__ == "__main__":
    unittest.main()
