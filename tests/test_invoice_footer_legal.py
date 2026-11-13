import os, shutil, tempfile, unittest

_D = tempfile.mkdtemp(prefix="gestion_foot_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"

from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import settings_service as ss  # noqa: E402
from app.printers import invoice_a4  # noqa: E402


class InvoiceFooterLegalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine.dispose(); init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def test_footer_wraps_without_losing_information(self):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        text = "  ·  ".join(["RCCM : BF OUA 2014 M05025", "IFU : 00013041A", "Régime fiscal : Réel Normal", "Direction : DGE/Centre",
                             "Compte Coris Bank BF42 0001 2345 6789 0123 4567 89", "Orange Money 70 43 46 43"])
        lines = invoice_a4.wrap_footer(text, 300)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(stringWidth(l, invoice_a4.FOOTER_FONT, invoice_a4.FOOTER_SIZE) <= 300 for l in lines))
        joined = " ".join(lines)
        for part in ("M05025", "00013041A", "Réel Normal", "DGE/Centre", "4567 89", "43 46 43"):
            self.assertIn(part, joined)
        self.assertEqual(invoice_a4.wrap_footer("", 300), [])

    def test_all_pharmacy_footer_fields(self):
        ss.set_setting("invoice_show_legal", "1")
        for k, v in (("shop_rccm", "BF OUA 01 2025 B13 12684"), ("shop_ifu", "00280675P"), ("shop_regime", "CMD"),
                     ("shop_direction", "DCI-OUAGA 8"), ("shop_agrement", "2026-050"), ("shop_footer_extra", "Pharmacie agréée")):
            ss.set_setting(k, v)
        txt = invoice_a4.legal_text()
        for part in ("00280675P", "Régime fiscal : CMD", "Direction : DCI-OUAGA 8", "N° d'agrément : 2026-050", "Pharmacie agréée"):
            self.assertIn(part, txt)


if __name__ == "__main__":
    unittest.main()
