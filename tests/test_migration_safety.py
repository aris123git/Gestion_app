"""Migration : ancienne base → colonnes ajoutées, version enregistrée, copie de sécurité.

Exécuté dans un processus séparé : la base est fixée à l'import de ``app.config``.
"""
import os, shutil, subprocess, sys, tempfile, textwrap, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent('''
    import sqlite3
    from app import config
    from app.database import connection

    config.ensure_directories()
    con = sqlite3.connect(str(config.DATABASE_FILE))
    con.execute("CREATE TABLE sales (id INTEGER PRIMARY KEY, ticket_number VARCHAR(40), total NUMERIC)")
    con.execute("INSERT INTO sales (ticket_number, total) VALUES ('OLD-1', 500)")
    con.commit(); con.close()
    connection.init_database()
    with connection.engine.connect() as c:
        cols = {r[1] for r in c.exec_driver_sql("PRAGMA table_info(sales)")}
        kept = c.exec_driver_sql("SELECT ticket_number FROM sales").scalar()
    assert "invoice_number" in cols and "delivery_number" in cols, cols
    assert kept == "OLD-1", kept
    assert connection.get_schema_version() == connection.SCHEMA_VERSION
    assert len(list(config.BACKUP_DIR.glob("pre_migration_v0_*.db"))) == 1
    connection.init_database()  # base à jour : pas de nouvelle copie
    assert len(list(config.BACKUP_DIR.glob("pre_migration_*.db"))) == 1
    connection.engine.dispose()
    print("OK")
''')


class MigrationTests(unittest.TestCase):
    def test_old_database_is_migrated_with_safety_copy(self):
        d = tempfile.mkdtemp(prefix="gestion_mig_")
        try:
            env = dict(os.environ, GESTION_DATA_DIR=d, NEXAPOS_SKIP_ACTIVATION="1", QT_QPA_PLATFORM="offscreen")
            r = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr[-1500:])
            self.assertIn("OK", r.stdout)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
