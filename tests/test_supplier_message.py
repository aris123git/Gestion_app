import os
import tempfile
import unittest
from unittest import mock

os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GESTION_DATA_DIR"] = tempfile.mkdtemp()


class SupplierMessageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from app.database.connection import init_database
        from app.database.seed import seed_all
        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()

    def test_format_short_and_table(self):
        from app.services.order_message import format_order
        short = format_order([("Riz", 8), ("Huile", 6)])
        self.assertEqual(short, "Bonjour, je voudrais commander : Riz × 8, Huile × 6.")
        table = format_order([(f"Produit {i}", i) for i in range(1, 8)])
        self.assertIn("```", table)
        self.assertIn("Produit 7", table)
        self.assertGreater(len(table.splitlines()), 8)

    def test_dialog_order_and_send(self):
        from app.controllers.product_controller import ProductController as PC
        from app.controllers.supplier_controller import SupplierController as SC
        from app.ui.dialogs import supplier_message_dialog as dm

        sid = SC.create({"name": "Fourn W", "phone": "+22670000009"}).id
        for i in range(7):
            PC.create({"name": f"Art {i}", "sale_price": 10, "purchase_price": 5, "quantity": 0, "min_stock": 3, "supplier_id": sid})
        dlg = dm.SupplierMessageDialog(sid, "Fourn W", "+22670000009")
        body = dlg.text.toPlainText()
        self.assertIn("```", body)          # 7 produits → tableau
        self.assertIn("Art 6", body)
        with mock.patch.object(dm.QDesktopServices, "openUrl") as op:
            dlg._send()
            self.assertIn("wa.me/22670000009", op.call_args[0][0].toString())
        # paiement : les crochets doivent être remplacés avant l'envoi
        dlg.model.setCurrentIndex(dlg.model.findData("paid"))
        with mock.patch.object(dm.QDesktopServices, "openUrl") as op, mock.patch.object(dm, "warn") as w:
            dlg._send()
            self.assertTrue(w.called)
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
