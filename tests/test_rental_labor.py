"""Location de matériel, main-d'œuvre (pointage / paie) et budget par poste."""
import os, shutil, tempfile, unittest
from datetime import datetime, timedelta

_D = tempfile.mkdtemp(prefix="gestion_rl_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import chantier_service as cs, labor_service as ls, rental_service as rs  # noqa: E402


class RentalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def _item(self, name, qty=2, rate=10000, deposit=20000):
        return rs.save_item(name=name, quantity=qty, rate_day=rate, deposit=deposit)

    def test_availability_and_overbooking(self):
        i = self._item("Bétonnière A", qty=2)
        now = datetime.now()
        rid = rs.create_rental(client_label="Zongo", due_date=now + timedelta(days=3), lines=[rs.LineInput(i, 2)])
        row = next(r for r in rs.list_items() if r.id == i)
        self.assertEqual((row.out, row.available), (2, 0))
        with self.assertRaises(ValueError):
            rs.create_rental(client_label="Autre", due_date=now + timedelta(days=1), lines=[rs.LineInput(i, 1)])
        rs.return_rental(rid)
        self.assertEqual(next(r for r in rs.list_items() if r.id == i).available, 2)

    def test_totals_deposit_and_late_fee(self):
        i = self._item("Echafaudage B", qty=1, rate=5000, deposit=10000)
        start = datetime.now() - timedelta(days=5) + timedelta(hours=1)
        rid = rs.create_rental(client_label="Ouedraogo", start_date=start, due_date=start + timedelta(days=3), lines=[rs.LineInput(i, 1)], paid=15000)
        s = rs.summary(rid)
        self.assertEqual((s.days_planned, s.base), (3, 15000))
        self.assertTrue(s.overdue)
        self.assertEqual(s.days_late, 2)
        self.assertEqual(s.late_fee, 10000)          # 2 jours × 5000
        self.assertEqual(s.deposit, 10000)
        done = rs.return_rental(rid, returned_at=start + timedelta(days=5), damage_fee=2000)
        self.assertEqual(done.total, 15000 + 10000 + 2000)
        # dû 12 000 → la caution de 10 000 le règle presque entièrement
        self.assertEqual(done.deposit_refunded, 0)
        self.assertEqual(done.balance, 2000)
        with self.assertRaises(ValueError):
            rs.return_rental(rid)

    def test_deposit_refund_and_due_today(self):
        i = self._item("Compacteur C", qty=1, rate=8000, deposit=30000)
        rid = rs.create_rental(client_label="X", due_date=datetime.now() + timedelta(hours=2), lines=[rs.LineInput(i, 1)], paid=8000)
        self.assertTrue(rs.summary(rid).due_today)
        self.assertIn(rid, [s.id for s in rs.alerts()["today"]])
        done = rs.return_rental(rid)
        self.assertEqual(done.deposit_refunded, 30000)
        self.assertEqual(done.balance, 0)

    def test_service_counter_and_repair(self):
        i = rs.save_item(name="Groupe D", quantity=1, rate_day=1000, service_every_days=3)
        rid = rs.create_rental(client_label="Y", start_date=datetime.now() - timedelta(days=4), due_date=datetime.now() + timedelta(hours=1), lines=[rs.LineInput(i, 1)])
        rs.return_rental(rid)
        self.assertTrue(next(r for r in rs.list_items() if r.id == i).needs_service)
        rs.record_repair(i, 5000)
        row = next(r for r in rs.list_items() if r.id == i)
        self.assertFalse(row.needs_service)
        self.assertEqual(row.repair_cost, 5000)

    def test_validation(self):
        i = self._item("Outil E", qty=1)
        with self.assertRaises(ValueError):
            rs.create_rental(client_label="", due_date=datetime.now() + timedelta(days=1), lines=[rs.LineInput(i, 1)])
        with self.assertRaises(ValueError):
            rs.create_rental(client_label="Z", due_date=datetime.now() - timedelta(days=1), lines=[rs.LineInput(i, 1)])
        with self.assertRaises(ValueError):
            rs.save_item(name="outil e")


class LaborBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        engine.dispose()

    def test_clock_in_and_payroll_with_advance(self):
        c1 = cs.create("Villa 1", client_label="A", amount=1_000_000, status="en_cours")
        c2 = cs.create("Villa 2", client_label="B", amount=500_000, status="en_cours")
        w = ls.save_worker(name="Traoré", trade="Soudeur", daily_rate=5000)
        d = datetime(2026, 11, 2)
        ls.clock_in(w, c1, date=d, days=1)
        ls.clock_in(w, c1, date=d + timedelta(days=1), days=1)
        ls.clock_in(w, c2, date=d + timedelta(days=2), days=0.5)
        with self.assertRaises(ValueError):
            ls.clock_in(w, c2, date=d, days=0.5)          # déjà 1 jour pointé ce jour-là
        ls.add_advance(w, 4000)
        line = ls.payroll_preview()[0]
        self.assertEqual((line.days, line.gross, line.advances, line.net), (2.5, 12500, 4000, 8500))
        ls.pay_worker(w)
        self.assertEqual(cs.summary(c1).spent, 10000)
        self.assertEqual(cs.summary(c2).spent, 2500)
        self.assertEqual(ls.payroll_preview(), [])
        self.assertEqual(ls.advances_due(w), 0)
        with self.assertRaises(ValueError):
            ls.pay_worker(w)

    def test_no_clock_in_on_quote(self):
        c = cs.create("Devis", client_label="A", amount=1000, status="devis")
        w = ls.save_worker(name="Kaboré", daily_rate=3000)
        with self.assertRaises(ValueError):
            ls.clock_in(w, c)

    def test_budget_vs_spent_alerts(self):
        c = cs.create("Budget", client_label="A", amount=1_000_000, status="en_cours")
        cs.set_budget(c, {"Matériel": 100000, "Main-d'œuvre": 50000, "Transport": 0})
        s = cs.summary(c)
        self.assertEqual(s.cost_budget, {"Matériel": 100000, "Main-d'œuvre": 50000})
        self.assertEqual(s.cost_budget_total, 150000)
        cs.add_expense(c, category="Matériel", amount=95000)
        self.assertTrue(any("presque épuisé" in a for a in cs.summary(c).alerts))
        cs.add_expense(c, category="Matériel", amount=20000)
        self.assertTrue(any("Budget dépassé" in a for a in cs.summary(c).alerts))
        cs.set_budget(c, {"Matériel": 0})
        self.assertNotIn("Matériel", cs.summary(c).cost_budget)

    def test_budget_from_quote(self):
        c = cs.create("Devis budget", client_label="A", status="devis", lines=[
            cs.LineInput("Ciment", 10, "sac", 8000, "Matériel"), cs.LineInput("Maçons", 5, "j", 6000, "Main-d'œuvre")])
        cs.budget_from_quote(c)
        self.assertEqual(cs.summary(c).cost_budget, {"Matériel": 80000, "Main-d'œuvre": 30000})


if __name__ == "__main__":
    unittest.main()
