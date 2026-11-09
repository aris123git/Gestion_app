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
