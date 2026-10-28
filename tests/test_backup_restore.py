"""Une sauvegarde doit se restaurer réellement ; une archive corrompue doit être refusée.

Processus séparé : la base est fixée à l'import de ``app.config``.
"""
import os, shutil, subprocess, sys, tempfile, textwrap, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent('''
    from app.database.connection import init_database, engine, session_scope
    from app.database.seed import seed_all
    from app.controllers.product_controller import ProductController
    from app.models.product import Product
    from app.services import backup_service as bs
    from sqlalchemy import select

    init_database(); seed_all()
    p = ProductController.create({"name": "Produit sauvé", "sale_price": 100, "purchase_price": 50, "quantity": 7})
    zip_path = bs.create_full_backup()
    assert bs.verify_backup(zip_path)

    with session_scope() as s:                      # on abîme les données après la sauvegarde
        row = s.get(Product, p.id); row.name = "Abîmé"; row.quantity = 0
    with session_scope() as s:
        assert s.scalar(select(Product).where(Product.name == "Produit sauvé")) is None

    bs.restore_backup(zip_path)
    init_database()
    with session_scope() as s:
        restored = s.scalar(select(Product).where(Product.name == "Produit sauvé"))
        assert restored is not None and float(restored.quantity) == 7

    bad = zip_path.with_name("corrompue.zip")       # archive tronquée → refusée
    bad.write_bytes(zip_path.read_bytes()[:200])
    try:
        bs.verify_backup(bad)
        raise SystemExit("archive corrompue acceptée")
    except bs.BackupError:
        pass
    engine.dispose()
    print("OK")
''')


class BackupRestoreTests(unittest.TestCase):
    def test_backup_roundtrip(self):
        d = tempfile.mkdtemp(prefix="gestion_bak_")
        try:
            env = dict(os.environ, GESTION_DATA_DIR=d, NEXAPOS_SKIP_ACTIVATION="1", QT_QPA_PLATFORM="offscreen")
            r = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:] + r.stdout[-500:])
            self.assertIn("OK", r.stdout)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
