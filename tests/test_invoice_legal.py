"""Option « TVA incluse + RCCM / IFU » sur la facture : absente par défaut, présente si cochée."""
import os, shutil, subprocess, tempfile, unittest
from datetime import datetime
from types import SimpleNamespace as NS

_D = tempfile.mkdtemp(prefix="gestion_legal_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pdf_text import pdf_text  # noqa: E402
from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.printers import invoice_a4 as ia  # noqa: E402
from app.services import settings_service  # noqa: E402


def _text(path):
    return pdf_text(path)


class LegalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database(); seed_all()
        settings_service.set_setting("shop_rccm", "BF-OUA-1"); settings_service.set_setting("shop_ifu", "0012A")

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def _sale(self):
        items = [NS(product_name="Gasoil", product_id=None, quantity=10, unit_price=1180, line_total=11800, tax_rate=18, purchase_price=0)]
        return NS(id=None, ticket_number="T1", date=datetime.now(), client_id=None, client=None, client_name="", client_phone="", items=items,
                  payments=[NS(method="Espèces", amount=11800)], subtotal=11800, discount=0, total=11800, amount_received=11800, change_due=0, cashier_name="", tax_total=0, user=None)

    def test_hidden_then_shown(self):
        for style in ("recu", "moderne_bleu"):
            settings_service.set_setting("invoice_show_legal", "0")
            p = ia.build_invoice_a4(self._sale(), path=config.TICKET_DIR / "l0.pdf", style_id=style)
            t = _text(p)
            self.assertNotIn("IFU", t); self.assertNotIn("TVA", t)
            settings_service.set_setting("invoice_show_legal", "1")
            p = ia.build_invoice_a4(self._sale(), path=config.TICKET_DIR / "l1.pdf", style_id=style)
            t = _text(p)
            self.assertIn("IFU", t); self.assertIn("TVA", t)


if __name__ == "__main__":
    unittest.main()
