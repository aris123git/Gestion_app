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

    def test_format_short(self):
        from app.services.order_message import format_order
        self.assertEqual(format_order([("Riz", 8), ("Huile", 6)]), "Bonjour, je voudrais commander : Riz × 8, Huile × 6.")

    def test_dialog_order_and_send(self):
        from app.controllers.product_controller import ProductController as PC
        from app.controllers.supplier_controller import SupplierController as SC
        from app.ui.dialogs import supplier_message_dialog as dm

        sid = SC.create({"name": "Fourn W", "phone": "+22670000009"}).id
        for i in range(7):
            PC.create({"name": f"Art {i}", "sale_price": 10, "purchase_price": 5, "quantity": 0, "min_stock": 3, "supplier_id": sid})
        dlg = dm.SupplierMessageDialog(sid, "Fourn W", "+22670000009")
        self.assertNotIn("```", dlg.text.toPlainText())
        self.assertIn("7 produits", dlg.text.toPlainText())   # beaucoup de produits → PDF en pièce jointe
        self.assertTrue(dlg.attach.isChecked())
        import app.ui.widgets.order_attach as oa
        with mock.patch.object(oa.QDesktopServices, "openUrl") as op, mock.patch.object(oa, "info"):
            dlg._send()
            self.assertIn("wa.me/22670000009", op.call_args[0][0].toString())
        from pathlib import Path
        import tempfile
        self.assertTrue((Path(tempfile.gettempdir()) / "commande.pdf").exists())
        # paiement : les crochets doivent être remplacés avant l'envoi
        dlg.model.setCurrentIndex(dlg.model.findData("paid"))
        with mock.patch.object(dm.QDesktopServices, "openUrl") as op, mock.patch.object(dm, "warn") as w:
            dlg._send()
            self.assertTrue(w.called)
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
