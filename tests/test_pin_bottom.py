"""Option « remplir la page » : signature / cachet / totaux tout en bas, avec peu de lignes."""
import os, shutil, tempfile, unittest

_D = tempfile.mkdtemp(prefix="gestion_pin_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine, SaleController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.printers import bon_enlevement as be, delivery_note as dn, invoice_a4 as ia  # noqa: E402
from app.printers.delivery_note import DELIVERY_STYLES  # noqa: E402


from pdf_text import content_size, lowest_y_ratio, page_count, page_texts  # noqa: E402


class PinBottomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database(); seed_all()
        pid = ProductController.create({"name": "Gasoil P", "sale_price": 800, "purchase_price": 700, "quantity": 100}).id
        res = SaleController.create_sale([CartLine(pid, "Gasoil P", 800, 1)], [PaymentLine("Espèces", 800)], amount_received=800)
        cls.sale = SaleController.get(res.sale_id)

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def test_invoice(self):
        a = ia.build_invoice_a4(self.sale, path=config.TICKET_DIR / "p_a.pdf", pin_bottom=False)
        b = ia.build_invoice_a4(self.sale, path=config.TICKET_DIR / "p_b.pdf", pin_bottom=True)
        self.assertLess(lowest_y_ratio(b, ["cachet"]), 0.25)
        self.assertGreater(lowest_y_ratio(a, ["Signature", "responsable"]), 0.4)

    def test_bon_enlevement(self):
        a = be.build_bon_enlevement(self.sale, path=config.TICKET_DIR / "p_c.pdf", overrides={"bon_pin_bottom": "0"})
        b = be.build_bon_enlevement(self.sale, path=config.TICKET_DIR / "p_d.pdf", overrides={"bon_pin_bottom": "1"})
        self.assertLess(lowest_y_ratio(b, ["cachet"]), 0.25)
        self.assertGreater(lowest_y_ratio(a, ["Commercial"]), 0.4)

    def test_delivery_note_all_styles_single_page(self):
        for style in DELIVERY_STYLES:
            with self.subTest(style=style.id):
                p = dn.build_delivery_note(self.sale, path=config.TICKET_DIR / f"p_{style.id}.pdf", style_id=style.id, overrides={"bl_pin_bottom": "1"})
                self.assertEqual(page_count(p), 1)          # pas de page blanche en plus


if __name__ == "__main__":
    unittest.main()


class FillRowsTests(PinBottomTests):
    def test_bon_fill_rows_single_page_and_taller_table(self):
        a = be.build_bon_enlevement(self.sale, path=config.TICKET_DIR / "f_a.pdf", overrides={"bon_fill_empty": "0"})
        b = be.build_bon_enlevement(self.sale, path=config.TICKET_DIR / "f_b.pdf", overrides={"bon_fill_empty": "1"})
        self.assertEqual(page_count(b), 1)
        self.assertGreater(content_size(b), content_size(a))        # des lignes (filets) en plus

    def test_delivery_fill_rows_all_styles(self):
        for style in DELIVERY_STYLES:
            with self.subTest(style=style.id):
                a = dn.build_delivery_note(self.sale, path=config.TICKET_DIR / f"fa_{style.id}.pdf", style_id=style.id, overrides={"bl_fill_empty": "0"})
                b = dn.build_delivery_note(self.sale, path=config.TICKET_DIR / f"fb_{style.id}.pdf", style_id=style.id, overrides={"bl_fill_empty": "1", "bl_pin_bottom": "1"})
                self.assertEqual(page_count(b), 1)
                self.assertGreaterEqual(content_size(b), content_size(a))


class LongInvoiceTests(PinBottomTests):
    def test_signature_box_on_every_page_same_number(self):
        pid = ProductController.create({"name": "Long P", "sale_price": 100, "purchase_price": 50, "quantity": 1000}).id
        res = SaleController.create_sale([CartLine(pid, f"Long P {i}", 100, 1) for i in range(70)], [PaymentLine("Espèces", 7000)], amount_received=7000)
        sale = SaleController.get(res.sale_id)
        path = ia.build_invoice_a4(sale, path=config.TICKET_DIR / "long.pdf", pin_bottom=True)
        texts = page_texts(path)
        self.assertGreaterEqual(len(texts), 2)
        number = ia.invoice_number(sale)
        for text in texts:
            self.assertIn("Signature et cachet", text)
            self.assertIn(str(number), text)
