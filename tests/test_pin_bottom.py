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


def _lowest_y_ratio(path, words) -> float:
    """Position verticale (0 = haut, 1 = bas) du dernier mot trouvé parmi ``words``."""
    import fitz
    doc = fitz.open(str(path))
    page = doc[len(doc) - 1]
    ys = [w[3] for w in page.get_text("words") if any(k.lower() in w[4].lower() for k in words)]
    return max(ys) / page.rect.height if ys else 0.0


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
        self.assertGreater(_lowest_y_ratio(b, ["cachet"]), 0.75)
        self.assertLess(_lowest_y_ratio(a, ["Signature", "responsable"]), 0.6)

    def test_bon_enlevement(self):
        a = be.build_bon_enlevement(self.sale, path=config.TICKET_DIR / "p_c.pdf", overrides={"bon_pin_bottom": "0"})
        b = be.build_bon_enlevement(self.sale, path=config.TICKET_DIR / "p_d.pdf", overrides={"bon_pin_bottom": "1"})
        self.assertGreater(_lowest_y_ratio(b, ["cachet"]), 0.75)
        self.assertLess(_lowest_y_ratio(a, ["Commercial", "client"]), 0.6)

    def test_delivery_note_all_styles_single_page(self):
        import fitz
        for style in DELIVERY_STYLES:
            with self.subTest(style=style.id):
                p = dn.build_delivery_note(self.sale, path=config.TICKET_DIR / f"p_{style.id}.pdf", style_id=style.id, overrides={"bl_pin_bottom": "1"})
                self.assertEqual(len(fitz.open(str(p))), 1)          # pas de page blanche en plus


if __name__ == "__main__":
    unittest.main()
