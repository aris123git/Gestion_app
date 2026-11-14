import os, shutil, tempfile, unittest
from datetime import date, datetime

_tmp = tempfile.mkdtemp()
os.environ["GESTION_DATA_DIR"] = _tmp
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class GasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.database.connection import engine, init_database
        from app.database.seed import seed_all
        engine.dispose(); init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        from app.database.connection import engine
        engine.dispose()
        shutil.rmtree(_tmp, ignore_errors=True)

    def setUp(self):
        from app.services import gas_service as gs
        gs.create_standard_lines()
        self.gs = gs
        lines = {l.name: l for l in gs.list_lines()}
        self.r6, self.r12 = lines["6 kg Recharge"], lines["12,5 kg Recharge"]
        gs.save_line(6, "recharge", 2000, 1778, line_id=self.r6.id)
        gs.save_line(12.5, "recharge", 5500, 5038, line_id=self.r12.id)

    def test_retail_day_sheet_and_stock(self):
        gs = self.gs
        d = datetime(2026, 1, 5, 9)
        gs.add_entry(self.r6.id, 100, d)
        gs.retail_sale(self.r6.id, 30, when=d)
        gs.retail_sale(self.r6.id, 10, 1900, when=d)
        gs.record_loss(self.r6.id, 2, "fuite", d)
        row = next(r for r in gs.day_sheet(date(2026, 1, 5)) if r["line_id"] == self.r6.id)
        self.assertEqual((row["si"], row["entry"], row["st"], row["sold"], row["sf"], row["lost"]), (0, 100, 100, 40, 58, 2))
        self.assertEqual(row["amount"], 30 * 2000 + 10 * 1900)
        nxt = next(r for r in gs.day_sheet(date(2026, 1, 6)) if r["line_id"] == self.r6.id)
        self.assertEqual(nxt["si"], 58)
        with self.assertRaises(gs.GasError):
            gs.retail_sale(self.r6.id, 1000)
        with self.assertRaises(gs.GasError):
            gs.record_loss(self.r6.id, 1, " ")

    def test_wholesaler_account_and_sentence(self):
        gs = self.gs
        gs.add_entry(self.r6.id, 200, datetime(2026, 2, 1, 8))
        wid = gs.save_wholesaler("Grossiste Test")
        gs.deliver(wid, [(self.r6.id, 98, None, 95)], datetime(2026, 2, 1, 10), paid=100000)
        a = gs.wholesaler_account(wid)
        self.assertEqual((a.delivered, a.empties_back, a.bottles_owed), (98, 95, 3))
        self.assertAlmostEqual(a.amount_due, 98 * 1778)
        self.assertAlmostEqual(a.balance, 98 * 1778 - 100000)
        self.assertIn("Il manque 3 vides", a.statement)
        self.assertIn("à payer", a.statement)
        gs.set_empties_back(gs.deliveries_of_day(date(2026, 2, 1))[0]["delivery_id"], self.r6.id, 98)
        gs.pay(wid, 98 * 1778 - 100000)
        a = gs.wholesaler_account(wid)
        self.assertTrue(a.statement.startswith("Compte juste : 98 vides reçues, 98 pleines remises"))
        with self.assertRaises(gs.GasError):
            gs.deliver(wid, [(self.r6.id, 10000, None, None)])
        self.assertEqual(gs.deliveries_of_day(date(2026, 2, 1))[0]["total"], 98 * 1778)

    def test_figures_profit_needs_cost(self):
        gs = self.gs
        gs.add_entry(self.r12.id, 50, datetime(2026, 3, 1, 8))
        gs.retail_sale(self.r12.id, 10, when=datetime(2026, 3, 1, 9))
        f = gs.figures(date(2026, 3, 1), date(2026, 3, 1))
        self.assertEqual(f["revenue"], 55000)
        self.assertIsNone(f["profit"])
        gs.save_line(12.5, "recharge", 5500, 5038, cost_price=5000, line_id=self.r12.id)
        self.assertEqual(gs.figures(date(2026, 3, 1), date(2026, 3, 1))["profit"], 5000)

    def test_trip_truck_stock_days_and_empties(self):
        gs = self.gs
        lines = {l.name: l for l in gs.list_lines()}
        c6 = lines["6 kg Consigné"]
        d1, d2 = datetime(2026, 4, 1, 8), datetime(2026, 4, 2, 9)
        tid = gs.start_trip([(self.r6.id, 700), (self.r12.id, 140), (c6.id, 10)], truck="Camion 1", driver="Ali", when=d1)
        self.assertEqual(gs.get_trip(tid).loaded, 850)
        depot = {l.id: l.stock for l in gs.list_lines()}            # le chargement n'entre pas dans le dépôt
        self.assertEqual(next(l.stock for l in gs.list_lines(trip_id=tid) if l.id == self.r6.id), 700)
        wid = gs.save_wholesaler("Gros Camion")
        gs.deliver(wid, [(self.r6.id, 100, None, 98)], d1, paid=50000, trip_id=tid)
        gs.retail_sale(self.r6.id, 20, when=d2, trip_id=tid)
        gs.retail_sale(c6.id, 3, 17000, when=d2, trip_id=tid)       # consigné : bouteille laissée au client, pas de vide
        gs.record_loss(self.r12.id, 1, "fuite", d2, trip_id=tid)
        with self.assertRaises(gs.GasError):
            gs.retail_sale(self.r6.id, 700, when=d2, trip_id=tid)   # plus que le camion ne contient
        days = gs.trip_days(tid)
        self.assertEqual([d["date"] for d in days], [d1.date(), d2.date()])
        self.assertAlmostEqual(days[0]["total"], 100 * 1778)
        self.assertEqual(gs.empties_proposed(tid), {6.0: 98 + 20})
        s = {r["name"]: r for r in gs.trip_summary(tid)}
        self.assertEqual(s["6 kg Recharge"]["remaining"], 700 - 100 - 20)
        sheet = {r["name"]: r for r in gs.day_sheet(d2.date(), trip_id=tid)}
        self.assertEqual(sheet["6 kg Recharge"]["sold"], 20)
        self.assertEqual({l.id: l.stock for l in gs.list_lines()}, depot)
        gs.close_trip(tid, {6.0: 120})                              # remise modifiée : 120 au lieu de 118
        self.assertEqual(gs.empties_returned(tid), [{"size_kg": 6.0, "proposed": 118, "handed": 120}])
        self.assertEqual(gs.get_trip(tid).status, "termine")
        back = {l.id: l.stock for l in gs.list_lines()}
        self.assertEqual(back[self.r6.id] - depot[self.r6.id], 580)  # le reste du camion retourne au dépôt
        with self.assertRaises(gs.GasError):
            gs.retail_sale(self.r6.id, 1, trip_id=tid)
        with self.assertRaises(gs.GasError):
            gs.close_trip(tid)

    def test_pdfs_and_general_figures(self):
        import tempfile
        from pathlib import Path
        from tests.pdf_text import pdf_text
        from app.printers import gas_docs
        from app.services.dashboard_service import DashboardService
        gs = self.gs
        d = datetime.now().replace(hour=9)
        tid = gs.start_trip([(self.r6.id, 50)], truck="Cam", driver="Ali", when=d)
        wid = gs.save_wholesaler("Gros PDF")
        gs.deliver(wid, [(self.r6.id, 10, None, 8)], d, paid=5000, trip_id=tid)
        gs.retail_sale(self.r6.id, 5, when=d, trip_id=tid)
        gs.record_loss(self.r6.id, 1, "bouteille percée", d, trip_id=tid)
        out = Path(tempfile.mkdtemp())
        t = pdf_text(gas_docs.build_trip_bandeau(tid, out / "a.pdf"))
        for part in ("Cam", "Ali", "Gros PDF", "bouteille percée", "SONABHY"):
            self.assertIn(part, t)
        both = pdf_text(gas_docs.build_day_sheet(d.date(), out / "b.pdf", tid))
        self.assertIn("Détaillants", both)
        self.assertIn("Grossistes", both)
        self.assertNotIn("Grossistes", pdf_text(gas_docs.build_day_sheet(d.date(), out / "b1.pdf", tid, "detaillants")).split("Sorties du jour")[0])
        only_g = pdf_text(gas_docs.build_day_sheet(d.date(), out / "b2.pdf", tid, "grossistes"))
        self.assertIn("Gros PDF", only_g)
        self.assertNotIn("S.F", only_g)
        self.assertIn("Il manque 2 vides", pdf_text(gas_docs.build_wholesaler_statement(wid, out / "c.pdf")))
        self.assertIn("bouteille percée", pdf_text(gas_docs.build_losses(d.date(), d.date(), out / "d.pdf")))
        before = DashboardService.financial_summary()
        gs.set_enabled(True)
        try:
            self.assertEqual(DashboardService.financial_summary()["revenue_today"], before["revenue_today"])   # gaz à part
            gs.set_include_in_totals(True)
            after = DashboardService.financial_summary()
            self.assertAlmostEqual(after["revenue_today"] - before["revenue_today"], gs.cash_in(d.date(), d.date()))
            self.assertGreater(after["client_debts"], before["client_debts"])
        finally:
            gs.set_include_in_totals(False)
            gs.set_enabled(False)

    def test_page_and_nav(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from app.services import gas_service as gs
        from app.ui.pages.gas_page import GasPage
        from app.ui.state import AppState
        self.assertFalse(gs.enabled())
        gs.set_enabled(True)
        try:
            state = AppState()
            state.can = lambda p: True
            page = GasPage(state)
            page.refresh()
            self.assertGreaterEqual(page.ltable.rowCount(), 6)
            from datetime import datetime as _dt
            tid = gs.start_trip([(page_line.id, 5) for page_line in gs.list_lines()[:1]], truck="Cam", when=_dt(2026, 5, 1, 8))
            page.refresh()
            self.assertEqual(page.source.count(), 2)          # Dépôt + voyage en cours
            page.source.setCurrentIndex(1)
            self.assertEqual(page._trip(), tid)
            page.ttable.selectRow(0)
            from app.ui.pages.gas_page import TripDaysDialog, CloseTripDialog
            TripDaysDialog(page, tid); CloseTripDialog(page, tid).apply(); self.assertEqual(gs.get_trip(tid).status, "termine")
            page.refresh()
            self.assertEqual(page.source.count(), 1)
            from app.ui.main_window import build_nav_items
            self.assertTrue(any(i[0] == "Gaz" for i in build_nav_items()))
        finally:
            gs.set_enabled(False)


if __name__ == "__main__":
    unittest.main()
