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
        self.assertEqual(int(ps.get(b)["number"][:3]), int(ps.get(a)["number"][:3]) + 1)
        d = ps.get(a)
        self.assertEqual(d["totals"].total, 280_000)
        from app.printers.proforma_doc import build_proforma_pdf
        txt = pdf_text(build_proforma_pdf(a, Path(_D) / "p.pdf"))
        for part in ("FACTURE PROFORMA", "SOGA SA", "00013041A", "Réel Normal", "DGE/Centre", "Livraison de la viande", "280 000",
                     "DEUX CENT QUATRE-VINGT MILLE", "Le Responsable", "KABORE John Didier", "70 43 46 43"):
            self.assertIn(part.lower(), txt.lower(), part)
        self.assertEqual(txt.lower().count("francs cfa"), 1)

    def test_sale_invoice_in_banner_model(self):
        from types import SimpleNamespace as NS
        from app.printers import invoice_a4 as ia
        items = [NS(product_name="Viande hachée", quantity=20, unit_price=4000, line_total=80000, tax_rate=0),
                 NS(product_name="Filet", quantity=20, unit_price=6000, line_total=120000, tax_rate=0)]
        sale = NS(items=items, subtotal=200000, discount=10000, total=190000, amount_received=0, change_due=0, ticket_number="T-1",
                  date=None, client_name="Client X", client_phone="", client_address="", client=None, cashier_name="")
        p = ia.build_invoice_a4(sale, path=Path(_D) / "b.pdf", style_id="commercial_banniere")
        txt = pdf_text(p).lower()
        for part in ("facture n°", "viande hachée", "client x", "sous-total", "remise", "total general", "190 000", "cent quatre-vingt-dix mille", "le responsable"):
            self.assertIn(part, txt, part)

    def test_header_logo_left_when_no_banner(self):
        from PIL import Image as PILImage
        from app.database.connection import session_scope
        from app.models.settings import ShopInfo
        from app.printers.proforma_doc import build_proforma_pdf
        a = ps.save([ps.LineInput("Test", 1, "kg", 1000)], client_name="Logo test")
        logo = Path(_D) / "logo.png"
        PILImage.new("RGB", (200, 100), "#1e3a8a").save(logo)
        with session_scope() as s_:
            shop = s_.get(ShopInfo, 1)
            old = shop.logo_path
            shop.logo_path = str(logo)
        try:
            with_logo = build_proforma_pdf(a, Path(_D) / "with_logo.pdf").read_bytes()
            self.assertIn(b"/Subtype /Image", with_logo)
        finally:
            with session_scope() as s_:
                s_.get(ShopInfo, 1).logo_path = old
        self.assertNotIn(b"/Subtype /Image", build_proforma_pdf(a, Path(_D) / "no_logo.pdf").read_bytes())

    def test_send_document_dialog(self):
        from unittest import mock
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from app.services import messaging_service as ms
        from app.ui.dialogs import send_document_dialog as sd
        pdf = Path(_D) / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        opened = []
        with mock.patch.object(sd.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())), \
                mock.patch.object(sd, "info", lambda *a, **k: None), mock.patch.object(sd, "warn", lambda *a, **k: None):
            dlg = sd.SendDocumentDialog(None, pdf, "70 43 46 43", "client@example.com", "Objet", "Bonjour é")
            self.assertFalse(sd.SendDocumentDialog(None, pdf, "abc", "", "", "x").send_whatsapp())     # numéro invalide
            self.assertTrue(dlg.send_whatsapp())
            self.assertTrue(opened[0].startswith("https://wa.me/") and "Bonjour" in opened[0])
            self.assertTrue(any(u.endswith("doc.pdf") for u in opened))                                  # le PDF s'ouvre pour être joint
            opened.clear()
            with mock.patch.object(ms, "email_configured", lambda: False):
                self.assertTrue(dlg.send_email())
            self.assertTrue(opened[0].startswith("mailto:client@example.com"))
            sent = []
            with mock.patch.object(ms, "email_configured", lambda: True), \
                    mock.patch.object(ms, "smtp_send", lambda to, subject, body, attachments=None: sent.append((to, subject, attachments))):
                self.assertTrue(dlg.send_email())
            self.assertEqual(sent, [("client@example.com", "Objet", [pdf])])
            self.assertFalse(sd.SendDocumentDialog(None, pdf, "", "pas-un-mail", "", "x").send_email())

    def test_smtp_send_attaches_pdf(self):
        from unittest import mock
        from app.services import messaging_service as ms
        pdf = Path(_D) / "att.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        captured = []

        class FakeSMTP:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def login(self, *a): pass
            def send_message(self, msg): captured.append(msg)

        with mock.patch.object(ms.smtplib, "SMTP_SSL", FakeSMTP), mock.patch.object(ms, "cfg", lambda k: "x" if "user" in k else ""):
            ms.smtp_send("a@b.com", "Sujet", "Corps", attachments=[pdf])
        self.assertEqual([p.get_filename() for p in captured[0].iter_attachments()], ["att.pdf"])

    def test_every_invoice_model_works_for_proforma(self):
        from app.printers import proforma_doc as pd
        a = ps.save([ps.LineInput("Viande hachée", 20, "kg", 4000, "")], client_name="SOGA SA", tax_label="BIC", tax_rate=5)
        models = [m for m, _ in pd.proforma_models()]
        self.assertIn("moderne_bleu", models)
        self.assertEqual(models[0], pd.BANNER_MODEL)
        for m in models:
            txt = pdf_text(pd.build_proforma_pdf(a, Path(_D) / f"m_{m}.pdf", m))
            self.assertIn("PROFORMA", txt.upper(), m)
            self.assertIn("SOGA", txt.upper(), m)
            self.assertIn("84 000", txt, m)                      # 80 000 + BIC 5 % = 84 000
            self.assertNotIn("N°00001", txt.replace(" ", ""), m)  # le numéro de la proforma, pas un numéro de facture
        pd.set_model("moderne_bleu")
        self.assertEqual(pd.get_model(), "moderne_bleu")
        pd.set_model("n_importe_quoi")
        self.assertEqual(pd.get_model(), "moderne_bleu")
        self.assertIn("MODERNE", "".join(l for l in [pd.get_model().upper()]))
        pd.set_model(pd.BANNER_MODEL)

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

    def test_convert_to_sale(self):
        from sqlalchemy import select
        from app.database.connection import session_scope
        from app.models.category import Category
        from app.models.client import Client
        from app.models.product import Product
        with session_scope() as s:
            cat = Category(name="Viandes"); s.add(cat); s.flush()
            prod = Product(name="Filet", category_id=cat.id, sale_price=6000, purchase_price=4000, quantity=100)
            cl = Client(name="SOGA"); s.add_all([prod, cl]); s.flush()
            pid_prod, cid = prod.id, cl.id
        pid = ps.save([ps.LineInput("filet", 20, "kg", 6000)], client_name="SOGA", client_id=cid)
        self.assertEqual(ps.suggest_products(pid), [pid_prod])
        with self.assertRaises(ValueError):
            ps.convert_to_sale(pid, [None])
        sale_id = ps.convert_to_sale(pid, [pid_prod], on_credit=True, user_id=1)
        d = ps.get(pid)
        self.assertEqual((d["status"], ), ("Facturée",))
        with session_scope() as s:
            self.assertEqual(float(s.get(Product, pid_prod).quantity), 80)
            self.assertEqual(float(s.get(Client, cid).debt), 120_000)
        with self.assertRaises(ValueError):
            ps.convert_to_sale(pid, [pid_prod])
        self.assertTrue(sale_id)

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
        # Choix d'un produit du catalogue : prix de vente par défaut, modifiable ; ligne libre inchangée
        from app.database.connection import session_scope
        from app.models.category import Category
        from app.models.product import Product
        with session_scope() as s:
            cat = Category(name="Test proforma"); s.add(cat); s.flush()
            s.add(Product(name="Gigot test", category_id=cat.id, sale_price=7500, purchase_price=5000, quantity=10))
        dlg = ProformaDialog(page)
        label, cdt, qty, unit, price, total = dlg._rows[0]
        label.setText("gigot TEST")
        label.editingFinished.emit()
        self.assertEqual(label.text(), "Gigot test")
        self.assertEqual(price.value(), 7500)
        qty.setValue(4)
        self.assertEqual(total.text().replace(" ", ""), "30000")
        price.setValue(7000)                      # prix modifiable
        self.assertEqual(dlg.values()[0][0].unit_price, 7000)
        label.editingFinished.emit()              # quitter la désignation ne doit ni écraser le prix saisi ni voler le curseur
        self.assertEqual(price.value(), 7000)
        dlg.show()
        price.setFocus()
        label.editingFinished.emit()
        self.assertTrue(price.hasFocus() or price.lineEdit().hasFocus() or dlg.focusWidget() is price)
        label.setText("Autre produit libre")
        label.editingFinished.emit()
        self.assertEqual(price.value(), 7000)
        dlg._add_row()
        free = dlg._rows[1]
        free[0].setText("Ligne libre")
        free[0].editingFinished.emit()
        self.assertEqual(free[4].value(), 0)
        ps.set_enabled(False)


if __name__ == "__main__":
    unittest.main()
