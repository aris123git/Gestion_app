"""Vérification des mises à jour (réseau simulé)."""
import os, shutil, tempfile, unittest

_D = tempfile.mkdtemp(prefix="gestion_upd_")
os.environ["GESTION_DATA_DIR"] = _D
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"

from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import update_service as us  # noqa: E402


class UpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database(); seed_all()

    @classmethod
    def tearDownClass(cls):
        engine.dispose(); shutil.rmtree(_D, ignore_errors=True)

    def test_versions_compare(self):
        self.assertGreater(us.version_tuple("1.10.0"), us.version_tuple("1.9.9"))
        self.assertEqual(us.version_tuple("v2.0"), (2, 0))

    def test_newer_and_same(self):
        newer = {"tag_name": "v99.0.0", "html_url": "https://x/r", "body": "Nouveautés", "assets": [{"name": "GestionCommerciale-v99.0.0.exe", "browser_download_url": "https://x/a.exe"}]}
        info = us.check_for_update(lambda url: newer)
        self.assertTrue(info.is_newer)
        self.assertEqual((info.latest, info.asset_url), ("99.0.0", "https://x/a.exe"))
        same = {"tag_name": "v" + info.current, "html_url": "https://x/r", "assets": []}
        self.assertFalse(us.check_for_update(lambda url: same).is_newer)

    def test_offline_gives_readable_error(self):
        def boom(url):
            raise OSError("offline")
        with self.assertRaises(RuntimeError) as ctx:
            us.check_for_update(boom)
        self.assertIn("internet", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
