"""Contrôle d'intégrité : base saine → aucune anomalie ; écarts provoqués → détectés."""
import os, shutil, tempfile, unittest

_D = tempfile.mkdtemp(prefix="gestion_integ_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"

from app.database.connection import engine, init_database, session_scope  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.controllers.product_controller import ProductController  # noqa: E402
from app.controllers.sale_controller import SaleController  # noqa: E402
from app.controllers.client_controller import ClientController  # noqa: E402
from app.models.client import Client  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.services import integrity_service as svc  # noqa: E402
from app.controllers.sale_controller import CartLine, PaymentLine  # noqa: E402


class IntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database(); seed_all()
        cls.p = ProductController.create({"name": "A", "sale_price": 100, "purchase_price": 50, "quantity": 20}).id
        SaleController.create_sale([CartLine(cls.p, "A", 100, 2)], [PaymentLine("Espèces", 200)], amount_received=200)

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def test_a_clean_database(self):
        self.assertEqual([i.message for i in svc.run_checks()], [])

    def test_b_detects_and_repairs_client_balance(self):
        c = ClientController.create({"name": "Zed", "phone": "70000001"})
        with session_scope() as s:
            s.get(Client, c.id).debt = 999
        issues = svc.run_checks()
        self.assertTrue(any(i.area == "Clients" for i in issues))
        self.assertGreaterEqual(svc.repair_client_balances(), 1)
        self.assertFalse(any(i.area == "Clients" for i in svc.run_checks()))

    def test_c_detects_negative_stock(self):
        with session_scope() as s:
            s.get(Product, self.p).quantity = -5
        self.assertTrue(any(i.area == "Stock" for i in svc.run_checks()))
        with session_scope() as s:
            s.get(Product, self.p).quantity = 18
        self.assertIn("Aucune anomalie", svc.summary())


if __name__ == "__main__":
    unittest.main()
