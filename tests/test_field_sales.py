"""Ventes en tournée : sortie, retour du soir, écart, commissions cumulées, boutiques visitées."""
import os, shutil, tempfile, unittest
from datetime import datetime, timedelta

_D = tempfile.mkdtemp(prefix="gestion_field_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.database.connection import engine, init_database, session_scope  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.category import Category  # noqa: E402
from app.models.client import Client  # noqa: E402
from app.models.field_sales import RULE_FIXED, RULE_PERCENT, SCOPE_CATEGORY, SCOPE_DEFAULT, SCOPE_PRODUCT  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.services import field_sales_service as fs  # noqa: E402


class FieldSalesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine.dispose(); init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def _admin(self):
        from app.models.user import User
        with session_scope() as s:
            return s.query(User).order_by(User.id).first().id

    def _product(self, name, price=20000, qty=100, category=None, min_price=0):
        with session_scope() as s:
            p = Product(name=name, sale_price=price, purchase_price=price * 0.6, quantity=qty, category_id=category, min_price=min_price)
            s.add(p); s.flush()
            return p.id

    def _seller(self, name):
        return fs.save_seller(name=name, phone="70 12 34 56")

    def _stock(self, pid):
        with session_scope() as s:
            return float(s.get(Product, pid).quantity)

    def test_reservation_blocks_overselling(self):
        pid = self._product("Carton Res", qty=30)
        a, b = self._seller("Vendeur Res A"), self._seller("Vendeur Res B")
        fs.open_run(a, [fs.LineInput(pid, 20)])
        self.assertEqual(self._stock(pid), 30)                          # pas retiré du stock avant la clôture
        choice = next(c for c in fs.product_choices() if c.id == pid)
        self.assertEqual(choice.available, 10)
        with self.assertRaises(ValueError):
            fs.open_run(b, [fs.LineInput(pid, 15)])
        fs.open_run(b, [fs.LineInput(pid, 10)])
        with self.assertRaises(ValueError):
            fs.open_run(a, [fs.LineInput(pid, 1)])                      # une seule sortie ouverte par vendeur

    def test_close_creates_sale_and_stock(self):
        pid = self._product("Carton Close", qty=50)
        sid = self._seller("Vendeur Close")
        run = fs.open_run(sid, [fs.LineInput(pid, 20)])
        line = fs.get_run_lines(run)[0]
        prev = fs.preview_close(run, {line.id: 5}, cash=300000)
        self.assertEqual((prev.expected, prev.shortage), (300000, 0))
        res = fs.close_run(run, {line.id: 5}, cash_received=300000)
        self.assertEqual(res.lines[0].sold, 15)
        self.assertEqual(self._stock(pid), 35)                          # 15 vendus sortent du stock, 5 restent
        row = next(r for r in fs.list_runs() if r.id == run)
        self.assertEqual((row.status, row.expected, row.shortage), ("cloture", 300000, 0))
        with self.assertRaises(ValueError):
            fs.close_run(run, {line.id: 5}, cash_received=0)            # déjà clôturée
        self.assertEqual(fs.reserved_quantities().get(pid, 0), 0)

    def test_return_larger_than_out_refused(self):
        pid = self._product("Carton Over", qty=10)
        run = fs.open_run(self._seller("Vendeur Over"), [fs.LineInput(pid, 5)])
        line = fs.get_run_lines(run)[0]
        with self.assertRaises(ValueError):
            fs.preview_close(run, {line.id: 6})

    def test_shortage_charged_to_seller_becomes_debt(self):
        pid = self._product("Carton Debt", qty=50)
        sid = self._seller("Vendeur Debt")
        run = fs.open_run(sid, [fs.LineInput(pid, 10)])
        line = fs.get_run_lines(run)[0]
        res = fs.close_run(run, {line.id: 0}, cash_received=150000, charge_shortage=True)   # attendu 200 000
        self.assertEqual(res.shortage, 50000)
        self.assertEqual(fs.seller_debt(sid), 50000)
        row = next(r for r in fs.list_runs() if r.id == run)
        self.assertTrue(row.charged)

    def test_shortage_absorbed_by_company_is_recorded_not_debt(self):
        pid = self._product("Carton Abs", qty=50)
        sid = self._seller("Vendeur Abs")
        run = fs.open_run(sid, [fs.LineInput(pid, 10)])
        line = fs.get_run_lines(run)[0]
        res = fs.close_run(run, {line.id: 0}, cash_received=190000)
        self.assertEqual(res.shortage, 10000)
        self.assertEqual(fs.seller_debt(sid), 0)
        self.assertFalse(next(r for r in fs.list_runs() if r.id == run).charged)

    def test_surplus_recorded(self):
        pid = self._product("Carton Plus", qty=50)
        run = fs.open_run(self._seller("Vendeur Plus"), [fs.LineInput(pid, 5)])
        line = fs.get_run_lines(run)[0]
        res = fs.close_run(run, {line.id: 0}, cash_received=120000)       # attendu 100 000
        self.assertEqual(res.shortage, -20000)

    def test_commission_rules_priority_and_mixed(self):
        with session_scope() as s:
            cat = Category(name="Cat Comm"); s.add(cat); s.flush(); cat_id = cat.id
        a = self._product("Produit pct", 20000, 100)                     # règle produit : 5 %
        b = self._product("Produit fixe", 15000, 100, category=cat_id)   # règle catégorie : 500 F / unité
        c = self._product("Produit défaut", 10000, 100)                  # règle par défaut : 2 %
        for scope, ref, kind, val in ((SCOPE_PRODUCT, a, RULE_PERCENT, 5), (SCOPE_CATEGORY, cat_id, RULE_FIXED, 500), (SCOPE_DEFAULT, None, RULE_PERCENT, 2)):
            fs.set_rule(scope, ref, kind, val)
        run = fs.open_run(self._seller("Vendeur Comm"), [fs.LineInput(a, 10), fs.LineInput(b, 20), fs.LineInput(c, 10)])
        lines = fs.get_run_lines(run)
        prev = fs.preview_close(run, {l.id: 0 for l in lines}, cash=10 * 20000 + 20 * 15000 + 10 * 10000)
        by = {l.name: l.commission for l in prev.lines}
        self.assertEqual(by["Produit pct"], 10000)       # 10 × 20 000 × 5 %
        self.assertEqual(by["Produit fixe"], 10000)      # 20 × 500
        self.assertEqual(by["Produit défaut"], 2000)     # 10 × 10 000 × 2 %
        self.assertEqual(prev.commission, 22000)
        fs.set_rule(SCOPE_DEFAULT, None, RULE_PERCENT, 0)
        self.assertFalse(any(r["scope"] == SCOPE_DEFAULT for r in fs.list_rules()))
        with self.assertRaises(ValueError):
            fs.set_rule(SCOPE_PRODUCT, a, RULE_PERCENT, 150)
        with self.assertRaises(ValueError):
            fs.set_rule(SCOPE_PRODUCT, None, RULE_PERCENT, 5)

    def test_commission_on_cash_option(self):
        pid = self._product("Carton Cash", 10000, 100)
        fs.set_rule(SCOPE_PRODUCT, pid, RULE_PERCENT, 10)
        sid = self._seller("Vendeur Cash")
        run = fs.open_run(sid, [fs.LineInput(pid, 10)])
        line = fs.get_run_lines(run)[0]
        try:
            fs.set_commission_on_cash(True)
            prev = fs.preview_close(run, {line.id: 0}, cash=50000)          # attendu 100 000, rapporté la moitié
            self.assertEqual(prev.commission, 5000)
            fs.set_commission_on_cash(False)
            self.assertEqual(fs.preview_close(run, {line.id: 0}, cash=50000).commission, 10000)
        finally:
            fs.set_commission_on_cash(False)

    def test_cumulative_commission_and_paying_periods(self):
        pid = self._product("Carton Pay", 10000, 500)
        fs.set_rule(SCOPE_PRODUCT, pid, RULE_PERCENT, 10)
        sid = self._seller("Vendeur Pay")
        for _ in range(3):
            run = fs.open_run(sid, [fs.LineInput(pid, 10)])
            fs.close_run(run, {fs.get_run_lines(run)[0].id: 0}, cash_received=100000)
        due = next(r for r in fs.commission_due() if r.seller_id == sid)
        self.assertEqual((due.runs, due.gross), (3, 30000))
        # anciennes sorties : on en recule une de 5 jours pour tester l'intervalle
        with session_scope() as s:
            from app.models.field_sales import FieldRun
            old = s.query(FieldRun).filter(FieldRun.seller_id == sid).order_by(FieldRun.id).first()
            old.closed_at = datetime.now() - timedelta(days=5)
        end = fs.day_range(datetime.now())[1]
        pay = fs.pay_commission(sid, end - timedelta(days=2), end, user_id=self._admin())         # seulement les 2 d'aujourd'hui
        self.assertEqual((pay.gross, pay.runs), (20000, 2))
        due = next(r for r in fs.commission_due() if r.seller_id == sid)
        self.assertEqual((due.runs, due.gross), (1, 10000))
        pay = fs.pay_last_days(sid, 30, user_id=self._admin())
        self.assertEqual(pay.gross, 10000)
        with self.assertRaises(ValueError):
            fs.pay_last_days(sid, 30, user_id=self._admin())
        with self.assertRaises(ValueError):
            fs.pay_last_days(sid, 0, user_id=self._admin())
        with self.assertRaises(ValueError):
            fs.pay_last_days(sid, 5)                                  # sans utilisateur

    def test_pay_commission_deducts_debt(self):
        pid = self._product("Carton Ded", 10000, 500)
        fs.set_rule(SCOPE_PRODUCT, pid, RULE_PERCENT, 10)
        sid = self._seller("Vendeur Ded")
        run = fs.open_run(sid, [fs.LineInput(pid, 10)])
        fs.close_run(run, {fs.get_run_lines(run)[0].id: 0}, cash_received=96000, charge_shortage=True)   # manque 4 000
        self.assertEqual(fs.seller_debt(sid), 4000)
        pay = fs.pay_last_days(sid, 1, deduct_debt=True, user_id=self._admin())
        self.assertEqual((pay.gross, pay.debt_deducted, pay.net_paid), (10000, 4000, 6000))
        self.assertEqual(fs.seller_debt(sid), 0)

    def test_contact_seller_whatsapp(self):
        pid = self._product("Carton Wa", 10000, 100)
        fs.set_rule(SCOPE_PRODUCT, pid, RULE_PERCENT, 10)
        sid = fs.save_seller(name="Moussa Wa", phone="70 99 88 77")
        self.assertEqual(fs.seller_message(sid), "Bonjour Moussa, ")
        run = fs.open_run(sid, [fs.LineInput(pid, 10)])
        fs.close_run(run, {fs.get_run_lines(run)[0].id: 0}, cash_received=100000)
        msg = fs.seller_message(sid)
        self.assertIn("10 000 F", msg)
        link = fs.seller_whatsapp_link(sid, msg)
        self.assertTrue(link.startswith("https://wa.me/22670998877?text="))
        nophone = fs.save_seller(name="Sans Tel")
        with self.assertRaises(ValueError):
            fs.seller_whatsapp_link(nophone, "x")

    def test_visits_and_prospects(self):
        pid = self._product("Carton Vis", qty=20)
        run = fs.open_run(self._seller("Vendeur Vis"), [fs.LineInput(pid, 5)])
        soon = datetime.now() + timedelta(days=2)
        fs.add_visit(run, "Boutique Awa", phone="70 11 22 33", area="Zogona", result="Intéressé", follow_up=soon)
        fs.add_visit(run, "Awa boutique", phone="70 11 22 33", result="Vendu", amount=25000)     # même téléphone → même boutique
        fs.add_visit(run, "Chez Paul", result="Refus")
        shops = {p.phone or p.shop: p for p in fs.prospects()}
        awa = shops["70 11 22 33"]
        self.assertEqual((awa.visits, awa.total, awa.last_result), (2, 25000, "Vendu"))
        with self.assertRaises(ValueError):
            fs.add_visit(run, "")
        fs.cancel_run(run)
        self.assertEqual(fs.list_visits(run), [])

    def test_validation(self):
        with self.assertRaises(ValueError):
            fs.save_seller(name="")
        sid = self._seller("Vendeur Val")
        with self.assertRaises(ValueError):
            fs.save_seller(name="vendeur val")
        with self.assertRaises(ValueError):
            fs.open_run(sid, [])
        pid = self._product("Carton Val", qty=5)
        with self.assertRaises(ValueError):
            fs.open_run(sid, [fs.LineInput(pid, 0)])
        run = fs.open_run(sid, [fs.LineInput(pid, 3)])
        fs.add_to_run(run, pid, 2)
        self.assertEqual(float(fs.get_run_lines(run)[0].qty_out), 5)
        with self.assertRaises(ValueError):
            fs.add_to_run(run, pid, 1)                                  # plus rien de disponible
        with self.assertRaises(ValueError):
            fs.delete_seller(sid)


if __name__ == "__main__":
    unittest.main()
