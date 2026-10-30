"""Tests : bon d'enlèvement (produits sélectionnés) et boutons d'impression."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace as NS

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_bon_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from pdf_text import pdf_text  # noqa: E402
from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.printers import bon_enlevement as be  # noqa: E402
from app.services import settings_service  # noqa: E402


def _sale():
    items = [NS(product_name=f"Produit {n}", product_id=None, quantity=n, unit_price=100, line_total=100 * n) for n in (1, 2, 3)]
    return NS(ticket_number="T1", date=datetime.now(), client_id=None, client_name="", client_phone="", items=items,
              payments=[NS(method="Espèces", amount=600)], subtotal=600, discount=0, total=600, amount_received=600, change_due=0, cashier_name="")


class BonTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def _text(self, path):

        return pdf_text(path)

    def test_only_selected_products(self) -> None:
        path = be.build_bon_enlevement(_sale(), path=config.TICKET_DIR / "a.pdf", selected=[1])
        text = self._text(path)
        self.assertIn("Produit 2", text)
        self.assertNotIn("Produit 1", text)
        self.assertNotIn("Produit 3", text)
        self.assertIn("200", text)  # total des seules lignes choisies

    def test_no_selection_raises(self) -> None:
        with self.assertRaises(ValueError):
            be.build_bon_enlevement(_sale(), path=config.TICKET_DIR / "b.pdf", selected=[])

    def test_empty_data_lines_hidden(self) -> None:
        text = self._text(be.build_bon_enlevement(_sale(), path=config.TICKET_DIR / "c.pdf"))
        for label in ("RCCM", "IFU", "COMPTE", "Contact", "Adresse :"):
            self.assertNotIn(label, text)
        self.assertNotIn("TOTAL GÉNÉRAL", text)  # pas d'acompte

    def test_signature_uses_names(self) -> None:
        sale = _sale()
        sale.client_id, sale.client_name = 3, "Société Faso Oil"
        text = self._text(be.build_bon_enlevement(sale, path=config.TICKET_DIR / "e.pdf", overrides={be.SETTING_COMMERCIAL: "Issa Ouédraogo"}))
        self.assertIn("Issa Ouédraogo", text)
        self.assertNotIn("Le Commercial", text)
        self.assertNotIn("Le client", text)
        fallback = self._text(be.build_bon_enlevement(_sale(), path=config.TICKET_DIR / "f.pdf"))
        self.assertIn("Le Commercial", fallback)

    def test_acompte(self) -> None:
        text = self._text(be.build_bon_enlevement(_sale(), path=config.TICKET_DIR / "d.pdf", overrides={be.SETTING_ACOMPTE_RATE: "2", be.SETTING_ACOMPTE_LABEL: "AC. BIC"}))
        self.assertIn("AC. BIC 2%", text)
        self.assertIn("TOTAL GÉNÉRAL", text)

    def test_dialog_buttons_print_selected(self) -> None:
        settings_service.save_shop_info(shop_type="Entreprise")
        settings_service.set_setting("bl_enabled", "1")  # le bon d'enlèvement n'est plus dans la fenêtre de vente
        from app.printers import half_a4_invoice as h
        from app.printers.thermal_printer import PrintResult
        from app.ui.dialogs.ticket_dialog import TicketDialog
        from pathlib import Path

        calls = []
        original = h.print_half_a4_invoice
        h.print_half_a4_invoice = lambda sale, shop=None, printer_name=None, pdf_path=None: (calls.append(pdf_path) or PrintResult(True, Path(pdf_path or "x.pdf"), "ok"))
        import app.ui.widgets.helpers as helpers
        import app.ui.dialogs.ticket_dialog as td
        td.info = td.warn = lambda *a, **k: None
        try:
            dialog = TicketDialog(_sale(), auto_print=False)
            self.assertIsNotNone(dialog.bon_list)
            dialog.bon_list.item(0).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Unchecked)
            self.assertEqual(dialog._selected_bon_lines(), [1, 2])
            dialog._print_all()
        finally:
            h.print_half_a4_invoice = original
        self.assertEqual(len(calls), 2)          # facture + bon de livraison
        self.assertIsNone(dialog.print_bon_button)
        self.assertIsNone(calls[0])              # la facture est générée par l'imprimante
        self.assertTrue(str(calls[1]).endswith(".pdf"))


if __name__ == "__main__":
    unittest.main()
