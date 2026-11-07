"""Sous-traitance : contrats, retenue de garantie, paiements → dépenses du chantier."""
import os, shutil, tempfile, unittest
from datetime import datetime, timedelta

_D = tempfile.mkdtemp(prefix="gestion_sub_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import chantier_service as cs, subcontract_service as ss  # noqa: E402


class SubcontractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def _setup(self, retention=10.0, amount=1_000_000):
        c = cs.create("Immeuble", client_label="X", amount=9_000_000, status="en_cours")
        st = ss.save_subcontractor(name=f"Plomb {c}", trade="Plombier")
        return c, ss.create_subcontract(c, st, "Plomberie complète", amount, retention_pct=retention)

    def test_payments_become_expenses_and_limits(self):
        c, sid = self._setup()
        s = ss.summary(sid)
        self.assertEqual((s.retention, s.payable_now), (100_000, 900_000))
        ss.add_payment(sid, 400_000, kind="Acompte")
        self.assertEqual(cs.summary(c).spent, 400_000)
        self.assertEqual(cs.summary(c).by_category["Sous-traitant"], 400_000)
        with self.assertRaises(ValueError):
            ss.add_payment(sid, 600_000)                   # dépasse 900 000 − 400 000
        ss.add_payment(sid, 500_000, kind="Solde")
        self.assertEqual(ss.summary(sid).payable_now, 0)
        self.assertEqual(ss.chantier_totals(c)["to_pay"], 0)

    def test_retention_release_only_after_reception(self):
        c, sid = self._setup()
        ss.add_payment(sid, 900_000, kind="Solde")
        with self.assertRaises(ValueError):
            ss.add_payment(sid, 100_000, kind="Libération de retenue")
        ss.set_status(sid, "termine")
        self.assertTrue(any("retenue" in a for a in ss.summary(sid).alerts))
        with self.assertRaises(ValueError):
            ss.add_payment(sid, 150_000, kind="Libération de retenue")
        ss.add_payment(sid, 100_000, kind="Libération de retenue")
        s = ss.summary(sid)
        self.assertEqual((s.retention_held, s.paid), (0, 1_000_000))
        self.assertEqual(cs.summary(c).spent, 1_000_000)

    def test_delete_payment_removes_expense(self):
        c, sid = self._setup()
        pid = ss.add_payment(sid, 200_000)
        ss.delete_payment(pid)
        self.assertEqual(cs.summary(c).spent, 0)
        self.assertEqual(ss.summary(sid).paid, 0)
        ss.delete_subcontract(sid)

    def test_validation_and_late_alert(self):
        c = cs.create("Devis seul", client_label="X", status="devis")
        st = ss.save_subcontractor(name="Elec Test")
        with self.assertRaises(ValueError):
            ss.create_subcontract(c, st, "Lot", 1000)       # devis, pas un marché
        m = cs.create("Marché", client_label="X", amount=1, status="en_cours")
        with self.assertRaises(ValueError):
            ss.create_subcontract(m, st, "", 1000)
        with self.assertRaises(ValueError):
            ss.create_subcontract(m, st, "Lot", 1000, retention_pct=50)
        sid = ss.create_subcontract(m, st, "Lot", 1000, end_planned=datetime.now() - timedelta(days=2))
        self.assertTrue(ss.summary(sid).late)
        with self.assertRaises(ValueError):
            ss.save_subcontractor(name="elec test")
        with self.assertRaises(ValueError):
            ss.delete_subcontractor(st)


if __name__ == "__main__":
    unittest.main()
