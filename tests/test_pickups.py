"""Enlèvements : validation → achat, livraisons aux stations, reste, clôture et perte."""
import os, shutil, tempfile, unittest
from datetime import date

_D = tempfile.mkdtemp(prefix="gestion_pickup_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pdf_text import pdf_text  # noqa: E402
from app import config  # noqa: E402
from app.controllers.client_controller import ClientController  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine, SaleController  # noqa: E402
from app.controllers.supplier_controller import SupplierController  # noqa: E402
from app.database.connection import engine, init_database, session_scope  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.models.stock import StockMovement  # noqa: E402
from app.services import accounting_service, integrity_service, pickup_service as ps, settings_service  # noqa: E402


class PickupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database(); seed_all()
        cls.supplier = SupplierController.create({"name": "SONABHY"}).id
        cls.client = ClientController.create({"name": "Station A", "phone": "70000010"}).id
        cls.client2 = ClientController.create({"name": "Station B", "phone": "70000011"}).id

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def setUp(self):
        self.product = ProductController.create({"name": f"Gasoil{id(self)}{os.urandom(2).hex()}", "sale_price": 800, "purchase_price": 700, "quantity": 0}).id

    def _deliver(self, item, qty, client):
        return SaleController.create_sale(
            [CartLine(self.product, "Gasoil", 800, qty)], [PaymentLine("Espèces", 800 * qty)],
            amount_received=800 * qty, client_id=client, pickup_links=[(item, qty)],
        )

    def test_full_cycle(self):
        pid = ps.create([ps.PickupLine(self.product, 1000)], supplier_id=self.supplier, note="test")
        row = ps.remaining(pid)[0]
        self.assertEqual((row.picked, row.delivered, row.left, row.unit_cost), (1000, 0, 1000, 700))
        # Produit suivi en stock et stock vide : la livraison avant validation est refusée (stock insuffisant).
        from app.controllers.sale_controller import InsufficientStockError
        with self.assertRaises(InsufficientStockError):
            self._deliver(row.item_id, 10, self.client)
        ps.mark_sent(pid)
        ps.validate(pid, amount_paid=0)
        with session_scope() as s:
            self.assertEqual(float(s.get(Product, self.product).quantity), 1000)
        self._deliver(row.item_id, 600, self.client)
        self.assertEqual(ps.remaining(pid)[0].left, 400)
        with self.assertRaises(ValueError):                       # plus que le reste
            self._deliver(row.item_id, 500, self.client2)
        with session_scope() as s:                                 # la vente refusée n'a rien changé
            self.assertEqual(float(s.get(Product, self.product).quantity), 400)
        self._deliver(row.item_id, 390, self.client2)
        self.assertEqual(ps.remaining(pid)[0].left, 10)
        self.assertEqual(len(ps.delivered_sales(pid)), 2)
        lost = ps.close(pid, "Évaporation", bearer="company")
        self.assertEqual(lost, 7000)
        r = ps.remaining(pid)[0]
        self.assertEqual((r.delivered, r.loss, r.left), (990, 10, 0))
        with session_scope() as s:
            self.assertEqual(float(s.get(Product, self.product).quantity), 0)
            self.assertTrue(s.query(StockMovement).filter(StockMovement.reason.like("Perte enlèvement%")).count() == 1)
        entries = accounting_service.generate_entries(date.today())
        self.assertTrue(all(e.balanced for e in entries))
        self.assertTrue(any(e.piece.startswith("BE-") for e in entries))
        self.assertEqual([i.message for i in integrity_service.run_checks()], [])
        listed = [x for x in ps.list_pickups() if x.id == pid][0]
        self.assertEqual((listed.picked, listed.delivered, listed.loss, listed.loss_percent), (1000, 990, 10, 1.0))
        self.assertTrue(listed.loss_alert)                         # 1 % > tolérance 0,5 %
        with self.assertRaises(ValueError):
            ps.close(pid, "x")
        rep = ps.loss_report(date(2020, 1, 1), date(2099, 1, 1))
        self.assertTrue(any(r[1] >= 1000 and r[2] >= 10 for r in rep))

    def test_loss_billed_to_clients(self):
        from app.models.client import Client
        pid = ps.create([ps.PickupLine(self.product, 1000)], supplier_id=self.supplier)
        ps.validate(pid)
        item = ps.remaining(pid)[0].item_id
        self._deliver(item, 600, self.client)
        self._deliver(item, 390, self.client2)
        shares, unbillable = ps.loss_allocation(pid)
        self.assertEqual(unbillable, [])
        self.assertEqual(round(sum(x.quantity for x in shares), 3), 10)
        self.assertEqual({x.client_id: x.unit_price for x in shares}, {self.client: 800, self.client2: 800})
        settings_service.set_setting("pickup_allow_billing", "1")
        company_loss = ps.close(pid, "Évaporation", bearer="client")
        self.assertEqual(company_loss, 0)
        with session_scope() as s:
            self.assertEqual(float(s.get(Product, self.product).quantity), 0)   # les 10 litres sont facturés, donc sortis
            self.assertGreater(float(s.get(Client, self.client).debt), 0)       # la station porte la perte à crédit
        r = ps.remaining(pid)[0]
        self.assertEqual((r.loss, r.left), (10, 0))
        entries = accounting_service.generate_entries(date.today())
        self.assertTrue(all(e.balanced for e in entries))
        number = [x for x in ps.list_pickups() if x.id == pid][0].number
        self.assertFalse(any(e.label.startswith(f"Perte sur enlèvement {number}") for e in entries))   # aucune charge pour l'entreprise
        self.assertEqual([i.message for i in integrity_service.run_checks()], [])
        self.assertEqual(ps.list_pickups()[0].loss_percent, 1.0)

    def test_info_only_default_changes_nothing(self):
        pid = ps.create([ps.PickupLine(self.product, 1000)], supplier_id=self.supplier, driver="Kaboré", truck="12 BB 3456", reference="BL-77")
        ps.validate(pid)
        item = ps.remaining(pid)[0].item_id
        self._deliver(item, 990, self.client)
        self.assertEqual(ps.default_bearer(), "info")
        self.assertEqual(ps.close(pid, "Évaporation"), 0)            # défaut : information seulement
        r = ps.remaining(pid)[0]
        self.assertEqual((r.delivered, r.loss, r.left), (990, 10, 0))   # l'écart est noté
        number = [x for x in ps.list_pickups() if x.id == pid][0].number
        with session_scope() as s:
            self.assertEqual(float(s.get(Product, self.product).quantity), 10)      # aucun mouvement de stock
            from app.models.pickup import Pickup
            pk = s.get(Pickup, pid)
            self.assertEqual((pk.driver, pk.truck, pk.reference, pk.loss_bearer), ("Kaboré", "12 BB 3456", "BL-77", "info"))
        entries = accounting_service.generate_entries(date.today())
        self.assertFalse(any(e.label.startswith(f"Perte sur enlèvement {number}") for e in entries))   # aucune écriture

    def test_tax_on_amount_due_and_default_paid(self):
        pid = ps.create([ps.PickupLine(self.product, 10, 700)], supplier_id=self.supplier, tax_rate=18)
        self.assertEqual(ps.amount_due(pid), (7000.0, 1260.0, 8260.0))
        ps.update_draft(pid, [ps.PickupLine(self.product, 10, 700)], supplier_id=self.supplier, tax_rate=5)
        self.assertEqual(ps.amount_due(pid), (7000.0, 350.0, 7350.0))
        from app.ui.dialogs.pickups_dialog import ValidatePickupDialog
        ht, tax, due = ps.amount_due(pid)
        dlg = ValidatePickupDialog(None, ht, tax)
        self.assertEqual(dlg.paid.value(), due)     # payé par défaut = montant à payer
        from app.printers import bon_enlevement as be
        path = be.build_pickup_bon(pid, config.TICKET_DIR / "tax_bon.pdf", True, "A4")
        text = pdf_text(path)
        self.assertIn("TAXE 5%", text.upper())
        ps.validate(pid, amount_paid=due)                                           # taxe payée en plus : pas de dette

    def test_billing_disabled_by_default_and_blocked(self):
        settings_service.set_setting("pickup_allow_billing", "0")
        settings_service.set_setting("pickup_loss_bearer", "client")
        self.assertFalse(ps.billing_allowed())
        self.assertEqual(ps.default_bearer(), "info")
        ProductController.update(self.product, {"sell_without_stock": True})
        pid = ps.create([ps.PickupLine(self.product, 5, 700)], supplier_id=self.supplier)
        ps.validate(pid)
        with self.assertRaises(ValueError):
            ps.close(pid, "Évaporation", bearer="client")

    def test_loss_without_any_client_stays_with_company(self):
        ProductController.update(self.product, {"sell_without_stock": True})
        pid = ps.create([ps.PickupLine(self.product, 50, 700)], supplier_id=self.supplier)
        ps.validate(pid)
        shares, unbillable = ps.loss_allocation(pid)
        self.assertEqual((shares, round(unbillable[0][1], 3)), ([], 50))
        settings_service.set_setting("pickup_allow_billing", "1")
        self.assertEqual(ps.close(pid, "Évaporation", bearer="client"), 50 * 700)

    def test_deliver_before_validation_without_stock(self):
        ProductController.update(self.product, {"sell_without_stock": True})
        pid = ps.create([ps.PickupLine(self.product, 100)], supplier_id=self.supplier)
        item = ps.remaining(pid)[0].item_id
        self._deliver(item, 100, self.client)                    # le chauffeur livre avec le bon, avant toute saisie
        self.assertEqual(ps.remaining(pid)[0].left, 0)
        ps.validate(pid, amount_paid=0)                           # le fournisseur signe, on valide ensuite
        self.assertEqual(ps.close(pid, "Évaporation"), 0)
        self.assertEqual([i.message for i in integrity_service.run_checks()], [])
        with self.assertRaises(ValueError):                       # clôturé : plus de livraison
            self._deliver(item, 1, self.client)

    def test_cancelled_delivery_frees_quantity(self):
        pid = ps.create([ps.PickupLine(self.product, 100)], supplier_id=self.supplier)
        ps.validate(pid, amount_paid=70000)
        item = ps.remaining(pid)[0].item_id
        res = self._deliver(item, 40, self.client)
        self.assertEqual(ps.remaining(pid)[0].left, 60)
        SaleController.cancel_sale(res.sale_id, restock=True, reason="erreur de saisie client")
        self.assertEqual(ps.remaining(pid)[0].left, 100)

    def test_draft_edit_and_delete(self):
        pid = ps.create([ps.PickupLine(self.product, 5)], supplier_id=self.supplier)
        ps.update_draft(pid, [ps.PickupLine(self.product, 9, 650)], supplier_id=self.supplier, note="x")
        self.assertEqual(ps.remaining(pid)[0].picked, 9)
        self.assertEqual(ps.remaining(pid)[0].unit_cost, 650)
        ps.delete_draft(pid)
        self.assertEqual(ps.remaining(pid), [])

    def test_pdf_with_and_without_prices(self):
        import subprocess
        from app.printers import bon_enlevement as be
        product = ProductController.create({"name": "Super95X", "sale_price": 900, "purchase_price": 750, "quantity": 0}).id
        supplier = SupplierController.create({"name": "SONABHY PDF"}).id
        pid = ps.create([ps.PickupLine(product, 2500)], supplier_id=supplier)
        from app import config
        for prices in (True, False):
            p = be.build_pickup_bon(pid, path=config.TICKET_DIR / f"pk_{prices}.pdf", show_prices=prices)
            text = pdf_text(p)
            self.assertIn("SONABHY PDF", text)
            self.assertIn("Super95X", text)
            self.assertEqual("P. TOTAL" in text, prices)


if __name__ == "__main__":
    unittest.main()

