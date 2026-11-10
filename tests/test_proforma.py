import os, shutil, tempfile, unittest
from pathlib import Path

_D = tempfile.mkdtemp(prefix="gestion_pf_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("NEXAGES_PRODUCT", None)

from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import proforma_service as ps, settings_service as ss  # noqa: E402
from tests.pdf_text import pdf_text  # noqa: E402


class ProformaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine.dispose(); init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def _make(self, **kw):
        fields = dict(client_name="SOGA SA", client_ifu="00013041A", client_rccm="BF OUA 2014 M05025", client_regime="Réel Normal",
                      client_division="DGE/Centre", client_address="Parcelle 12", subject="Livraison de la viande.",
                      responsible="KABORE John Didier", responsible_phone="70 43 46 43")
        fields.update(kw)
        return ps.save([ps.LineInput("Viande hachée", 20, "kg", 4000), ps.LineInput("Faux filet", 20, "kg", 4000), ps.LineInput("Filet", 20, "kg", 6000)], **fields)

    def test_numbering_totals_and_pdf(self):
        a, b = self._make(), self._make()
        self.assertEqual([ps.get(a)["number"][:3], ps.get(b)["number"][:3]], ["001", "002"])
        d = ps.get(a)
        self.assertEqual(d["totals"].total, 280_000)
        from app.printers.proforma_doc import build_proforma_pdf
        txt = pdf_text(build_proforma_pdf(a, Path(_D) / "p.pdf"))
        for part in ("FACTURE PROFORMA", "SOGA SA", "00013041A", "Réel Normal", "DGE/Centre", "Livraison de la viande", "280 000",
                     "DEUX CENT QUATRE-VINGT MILLE", "Le Responsable", "KABORE John Didier", "70 43 46 43"):
            self.assertIn(part.lower(), txt.lower(), part)
        self.assertEqual(txt.lower().count("francs cfa"), 1)

    def test_tax_and_cdt(self):
        pid = ps.save([ps.LineInput("Gants latex", 10, "", 2000, "B/100")], client_name="Client", tax_label="BIC", tax_rate=2)
        d = ps.get(pid)
        self.assertEqual((d["totals"].subtotal, d["totals"].tax, d["totals"].total), (20_000, 400, 20_400))
        from app.printers.proforma_doc import build_proforma_pdf
        txt = pdf_text(build_proforma_pdf(pid, Path(_D) / "q.pdf"))
        for part in ("CDT", "B/100", "MONTANT HT", "BIC 2 %", "MONTANT TTC", "20 400"):
            self.assertIn(part.lower(), txt.lower(), part)

    def test_validation_duplicate_status(self):
        with self.assertRaises(ValueError):
            ps.save([], client_name="X")
        with self.assertRaises(ValueError):
            ps.save([ps.LineInput("A", 1, "", 10)], client_name=" ")
        pid = self._make()
        new = ps.duplicate(pid)
        self.assertNotEqual(ps.get(new)["number"], ps.get(pid)["number"])
        ps.set_status(pid, "Acceptée")
        self.assertEqual(ps.get(pid)["status"], "Acceptée")
        ps.delete(new)
        self.assertNotIn(new, [x["id"] for x in ps.list_all()])

    def test_ui_page_and_nav(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from app.ui.main_window import build_nav_items
        from app.ui.pages.proformas_page import ProformasPage, ProformaDialog
        from app.ui.state import AppState
        state = AppState(); state.auth.login("admin", "admin")
        ps.set_enabled(False)
        self.assertFalse(any("Proforma" in str(i[0]) for i in build_nav_items()))
        ps.set_enabled(True)
        self.assertTrue(any("Proforma" in str(i[0]) for i in build_nav_items()))
        page = ProformasPage(state)
        self.assertGreaterEqual(page.table.rowCount(), 1)
        dlg = ProformaDialog(page, ps.get(next(x["id"] for x in ps.list_all() if x["client"] == "SOGA SA")))
        lines, date, fields = dlg.values()
        self.assertEqual(fields["client_name"], "SOGA SA")
        self.assertEqual(len(lines), 3)
        ps.set_enabled(False)


if __name__ == "__main__":
    unittest.main()
