"""Alertes (stock, dettes, rappels) et rappels saisis à la main."""
import os, tempfile, unittest
from datetime import date, timedelta

os.environ["GESTION_DATA_DIR"] = tempfile.mkdtemp()
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class NotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.database.connection import init_database
        from app.database.seed import seed_all
        from app.controllers.product_controller import ProductController as PC

        init_database()
        seed_all()
        cls.low = PC.create({"name": "Riz", "sale_price": 1000, "purchase_price": 800, "quantity": 3, "min_stock": 5}).id
        cls.out = PC.create({"name": "Huile", "sale_price": 1000, "purchase_price": 800, "quantity": 0, "min_stock": 2}).id
        PC.create({"name": "Sucre", "sale_price": 1000, "purchase_price": 800, "quantity": 50, "min_stock": 5})

    def test_stock_alerts(self):
        from app.services import notification_service as ns

        texts = [a.text for a in ns.alerts() if a.kind == ns.KIND_STOCK]
        self.assertTrue(any("Huile" in x and "rupture" in x for x in texts))
        self.assertTrue(any("Riz" in x and "bas" in x for x in texts))
        self.assertFalse(any("Sucre" in x for x in texts))
        ns.set_enabled(ns.KIND_STOCK, False)
        self.assertFalse([a for a in ns.alerts() if a.kind == ns.KIND_STOCK])
        ns.set_enabled(ns.KIND_STOCK, True)

    def test_permission_hides_stock_alerts(self):
        from app.services import notification_service as ns

        self.assertFalse([a for a in ns.alerts(lambda _p: False) if a.kind == ns.KIND_STOCK])

    def test_reminders_due_upcoming_done_and_repeat(self):
        from app.services import notification_service as ns

        today = date.today()
        a = ns.add_reminder("Payer le loyer", today)
        b = ns.add_reminder("Plus tard", today + timedelta(days=5))
        c = ns.add_reminder("Chaque semaine", today - timedelta(days=1), ns.REPEAT_WEEKLY)
        due = {x.reminder_id for x in ns.alerts() if x.kind == ns.KIND_REMINDER}
        self.assertIn(a, due)
        self.assertIn(c, due)
        self.assertNotIn(b, due)
        self.assertIn(b, {x.reminder_id for x in ns.alerts(include_upcoming=True)})
        ns.mark_done(a)
        ns.mark_done(c)
        due = {x.reminder_id for x in ns.alerts() if x.kind == ns.KIND_REMINDER}
        self.assertNotIn(a, due)
        self.assertNotIn(c, due)     # répété : reporté à la semaine suivante
        ns.delete_reminder(b)
        with self.assertRaises(ValueError):
            ns.add_reminder("  ", today)

    def test_overdue_debt_alert(self):
        from app.database.connection import session_scope
        from app.models.client import Client
        from app.models.debt import Debt
        from app.services import notification_service as ns

        with session_scope() as s:
            cl = Client(name="M. Ouédraogo")
            s.add(cl)
            s.flush()
            s.add(Debt(client_id=cl.id, amount_initial=5000, amount_remaining=5000, due_date=date.today() - timedelta(days=10)))
        texts = [a.text for a in ns.alerts() if a.kind == ns.KIND_DEBT]
        self.assertTrue(any("Ouédraogo" in x for x in texts))

    def test_dialog_builds(self):
        from PySide6.QtWidgets import QApplication
        from app.ui.dialogs.alerts_dialog import AlertsDialog

        QApplication.instance() or QApplication([])
        d = AlertsDialog(None, lambda _p: True)
        self.assertGreaterEqual(d.list.count(), 1)


if __name__ == "__main__":
    unittest.main()
