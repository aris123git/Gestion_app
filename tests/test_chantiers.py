"""Chantiers / marchés : devis → marché, dépenses, encaissements, avenants, avancement, résultat."""
import os, shutil, tempfile, unittest
from datetime import datetime, timedelta

_D = tempfile.mkdtemp(prefix="gestion_chantiers_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.database.connection import engine, init_database, session_scope  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.expense import Expense  # noqa: E402
from app.services import chantier_service as cs  # noqa: E402


class ChantierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def _market(self, amount=1_000_000):
        return cs.create("Villa test", client_label="M. Zongo", amount=amount, status="en_cours")

    def test_quote_to_market_flow(self):
        cid = cs.create("Hangar", client_label="X", status="devis", lines=[
            cs.LineInput("Fondations", 1, "forfait", 400_000, "Matériel"), cs.LineInput("Charpente", 2, "u", 150_000, "Matériel")])
        self.assertEqual(cs.summary(cid).budget, 700_000)
        with self.assertRaises(ValueError):
            cs.add_expense(cid, category="Matériel", amount=1000)            # pas de dépense avant le marché
        with self.assertRaises(ValueError):
            cs.add_payment(cid, amount=1000)
        cs.set_status(cid, "accepte")
        cs.convert_to_market(cid)
        s = cs.summary(cid)
        self.assertEqual((s.status, s.contract), ("en_cours", 700_000))
        self.assertGreater(len(cs.list_summaries(status="en_cours")), 0)
        refused = cs.create("Refusé", status="devis", amount=50_000)
        cs.set_status(refused, "refuse")
        self.assertNotIn("refuse", {x.status for x in cs.list_summaries() if x.status in ("en_cours",)})
        with self.assertRaises(ValueError):
            cs.convert_to_market(cid)                                           # déjà un marché

    def test_money_flow_and_margin(self):
        cid = self._market(1_000_000)
        cs.add_payment(cid, amount=300_000, kind="Avance", method="Mobile Money")
        cs.add_expense(cid, category="Matériel", label="Ciment", amount=200_000, supplier="Quincaillerie")
        cs.add_expense(cid, category="Main-d'œuvre", worker="Ali", days=10, daily_rate=5000)           # 50 000
        credit = cs.add_expense(cid, category="Transport", amount=100_000, amount_paid=40_000)         # 60 000 de dette
        s = cs.summary(cid)
        self.assertEqual((s.received, s.remaining_to_receive), (300_000, 700_000))
        self.assertEqual((s.spent, s.paid_out, s.supplier_debt), (350_000, 290_000, 60_000))
        self.assertEqual((s.margin, s.cash), (650_000, 10_000))
        self.assertEqual(s.by_category["Main-d'œuvre"], 50_000)
        cs.pay_expense(credit, 60_000)
        self.assertEqual(cs.summary(cid).supplier_debt, 0)
        with self.assertRaises(ValueError):
            cs.pay_expense(credit, 1)
        with self.assertRaises(ValueError):
            cs.add_payment(cid, amount=800_000)                                  # dépasserait le marché
        with self.assertRaises(ValueError):
            cs.delete(cid)                                                       # de l'argent est engagé

    def test_addendum_changes_contract(self):
        cid = self._market(500_000)
        cs.add_addendum(cid, label="Mur supplémentaire", amount=80_000)
        cs.add_addendum(cid, label="Moins-value carrelage", amount=-20_000)
        s = cs.summary(cid)
        self.assertEqual((s.contract, s.addenda_total), (560_000, 60_000))
        cs.add_expense(cid, category="Matériel", amount=100_000)
        self.assertEqual(cs.summary(cid).margin, 460_000)
        with self.assertRaises(ValueError):
            cs.add_addendum(cid, label="", amount=5)

    def test_progress_modes_and_alerts(self):
        cid = self._market(1_000_000)
        cs.set_progress(cid, 50)
        cs.add_expense(cid, category="Matériel", amount=800_000)               # 80 % dépensé pour 50 % d'avancement
        s = cs.summary(cid)
        self.assertEqual(s.progress_pct, 50)
        self.assertTrue(any("Dérapage" in a for a in s.alerts))
        cs.add_expense(cid, category="Matériel", amount=300_000)
        self.assertTrue(any("perte" in a for a in cs.summary(cid).alerts))
        # lots
        c2 = self._market()
        a = cs.add_lot(c2, "Fondation", 20); cs.add_lot(c2, "Murs", 30); cs.add_lot(c2, "Toiture", 50)
        with self.assertRaises(ValueError):
            cs.add_lot(c2, "Trop", 10)
        cs.update(c2, progress_mode="lots")
        cs.set_lot_done(a, True)
        self.assertEqual(cs.summary(c2).progress_pct, 20)
        cs.set_progress(c2, 10)                                                # repasse en manuel
        self.assertEqual(cs.summary(c2).progress_pct, 10)

    def test_milestones_late_alert(self):
        cid = self._market(1_000_000)
        cs.add_milestone(cid, "À la signature", 30, datetime.now() - timedelta(days=10))
        cs.add_milestone(cid, "À la réception", 70, datetime.now() + timedelta(days=60))
        with self.assertRaises(ValueError):
            cs.add_milestone(cid, "Trop", 10)
        s = cs.summary(cid)
        self.assertEqual([p for _l, p, _c, _d in s.planned_vs_received], [300_000, 700_000])
        self.assertTrue(any("retard" in a for a in s.alerts))
        cs.add_payment(cid, amount=300_000, kind="Avance")
        self.assertFalse(any("retard" in a for a in cs.summary(cid).alerts))

    def test_attachment_and_receipt_numbers(self):
        cid = self._market()
        src = os.path.join(_D, "recu.txt")
        with open(src, "w") as fh:
            fh.write("reçu")
        eid = cs.add_expense(cid, category="Matériel", amount=1000, attachment_source=src)
        with session_scope() as session:
            from app.models.chantier import ChantierExpense
            rel = session.get(ChantierExpense, eid).attachment
        self.assertTrue(cs.attachment_path(rel).is_file())
        p1 = cs.add_payment(cid, amount=1000); p2 = cs.add_payment(cid, amount=1000)
        with session_scope() as session:
            from app.models.chantier import ChantierPayment
            n1, n2 = session.get(ChantierPayment, p1).number, session.get(ChantierPayment, p2).number
        self.assertNotEqual(n1, n2)

    def test_global_result_separates_overheads(self):
        before = cs.global_result()
        cid = self._market(1_000_000)
        cs.add_payment(cid, amount=400_000)
        cs.add_expense(cid, category="Matériel", amount=100_000)
        with session_scope() as session:
            session.add(Expense(category="Loyer", label="Loyer atelier", amount=30_000, date=datetime.now()))
        after = cs.global_result()
        self.assertEqual(after.received - before.received, 400_000)
        self.assertEqual(after.overheads - before.overheads, 30_000)
        self.assertEqual(after.net_cash - before.net_cash, 400_000 - 100_000 - 30_000)
        self.assertEqual(after.net_profit - before.net_profit, (1_000_000 - 100_000) - 30_000)

    def test_pdfs(self):
        from pdf_text import page_texts
        from app.printers import chantier_docs as docs
        cid = cs.create("Dalle atelier", client_label="Mme Ouedraogo", status="devis", lines=[cs.LineInput("Dalle béton", 20, "m²", 15_000, "Matériel")])
        quote = docs.build_quote(cid, config.TICKET_DIR / "t_devis.pdf")
        text = " ".join(page_texts(quote))
        self.assertIn("DEVIS", text); self.assertIn("Dalle", text)
        cs.convert_to_market(cid)
        pid = cs.add_payment(cid, amount=100_000, kind="Avance")
        cs.add_expense(cid, category="Matériel", amount=50_000)
        self.assertIn("REÇU", " ".join(page_texts(docs.build_receipt(pid, config.TICKET_DIR / "t_recu.pdf"))))
        report = " ".join(page_texts(docs.build_report(cid, config.TICKET_DIR / "t_rapport.pdf")))
        self.assertIn("RAPPORT", report); self.assertIn("Reste à encaisser", report)


if __name__ == "__main__":
    unittest.main()
