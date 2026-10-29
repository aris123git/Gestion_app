"""Chauffeurs / camions : listes de Paramètres, choix sur la vente, consultation ultérieure, jamais imprimés."""
import os, shutil, subprocess, tempfile, unittest

_D = tempfile.mkdtemp(prefix="gestion_transport_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from app import config  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine, SaleController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import transport_service as ts  # noqa: E402


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        init_database(); seed_all()
        cls.product = ProductController.create({"name": "Gasoil T", "sale_price": 800, "purchase_price": 700, "quantity": 100}).id

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def _sale(self):
        return SaleController.create_sale([CartLine(self.product, "Gasoil T", 800, 1)], [PaymentLine("Espèces", 800)], amount_received=800)

    def test_lists(self):
        ts.add("driver", "Ouédraogo"); ts.add("driver", "ouédraogo"); ts.add("truck", "11 AA 1234")
        self.assertEqual(ts.list_names("driver"), ["Ouédraogo"])         # pas de doublon
        ts.add("driver", "Kaboré"); ts.remove("driver", "Ouédraogo")
        self.assertEqual(ts.list_names("driver"), ["Kaboré"])
        self.assertEqual(ts.list_names("truck"), ["11 AA 1234"])

    def test_sale_keeps_transport_and_is_searchable_but_not_printed(self):
        ts.add("driver", "Sawadogo Issa")
        res = self._sale()
        ts.set_sale_transport(res.sale_id, "Sawadogo Issa", "12 BB 9999")
        self.assertEqual(ts.get_sale_transport(res.sale_id), ("Sawadogo Issa", "12 BB 9999"))
        self.assertTrue(any(s.id == res.sale_id for s in SaleController.list(search="12 BB 9999")))
        self.assertTrue(any(s.id == res.sale_id for s in SaleController.list(search="sawadogo issa")))
        from app.printers import delivery_note as dn, invoice_a4 as ia
        sale = SaleController.get(res.sale_id)
        for path in (ia.build_invoice_a4(sale, path=config.TICKET_DIR / "t_inv.pdf"), dn.build_delivery_note(sale, path=config.TICKET_DIR / "t_bl.pdf")):
            text = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True).stdout
            self.assertNotIn("9999", text); self.assertNotIn("Sawadogo Issa", text)

    def test_ticket_dialog_selects_and_saves(self):
        from app.ui.dialogs.ticket_dialog import TicketDialog
        ts.add("truck", "13 CC 0001")
        res = self._sale()
        sale = SaleController.get(res.sale_id)
        d = TicketDialog(sale, auto_print=False)
        d.truck_combo.setCurrentText("13 CC 0001")
        self.assertEqual(ts.get_sale_transport(res.sale_id)[1], "13 CC 0001")
        d2 = TicketDialog(SaleController.get(res.sale_id), auto_print=False)       # réouverture plus tard
        self.assertEqual(d2.truck_combo.currentText(), "13 CC 0001")


if __name__ == "__main__":
    unittest.main()
