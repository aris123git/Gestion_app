"""Tests : bon de livraison (12 styles), numérotation, boutons d'impression."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace as NS

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_bl_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.printers import delivery_note as dn  # noqa: E402
from app.services import settings_service  # noqa: E402


def _sale(n=3, known=True):
    items = [NS(product_name=f"Produit {i}", product_id=None, quantity=i, unit_price=100, line_total=100 * i) for i in range(1, n + 1)]
    client = NS(id=7, name="Awa Traoré", phone="70112233", phone2="", address="Secteur 4, Ouaga", email="awa@ex.com")
    return NS(id=None, ticket_number="T1", date=datetime.now(), client_id=7 if known else None, client=client if known else None,
              client_name="Awa Traoré" if known else "", client_phone="70112233" if known else "", items=items,
              payments=[], subtotal=600, discount=0, total=600)


class DeliveryNoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(_DATA_DIR, ignore_errors=True)

    def test_all_styles_render(self):
        for st in dn.DELIVERY_STYLES:
            for n in (1, 3, 60):
                p = dn.build_delivery_note(_sale(n), style_id=st.id, path=config.TICKET_DIR / f"{st.id}_{n}.pdf")
                self.assertTrue(p.is_file() and p.stat().st_size > 800, st.id)

    def test_subset_and_anonymous(self):
        p = dn.build_delivery_note(_sale(known=False), selected=[0], path=config.TICKET_DIR / "sub.pdf")
        self.assertTrue(p.is_file())
        with self.assertRaises(ValueError):
            dn.build_delivery_note(_sale(), selected=[], path=config.TICKET_DIR / "none.pdf")

    def test_toggles(self):
        self.assertFalse(dn.is_enabled())
        settings_service.set_setting(dn.SETTING_ENABLED, "1")
        self.assertTrue(dn.is_enabled())
        self.assertTrue(dn.in_print_all())
        settings_service.set_setting(dn.SETTING_IN_ALL, "0")
        self.assertFalse(dn.in_print_all())


if __name__ == "__main__":
    unittest.main()
