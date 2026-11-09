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

    def test_no_release_is_not_reported_as_offline(self):
        import urllib.error
        def nope(url):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        with self.assertRaises(RuntimeError) as ctx:
            us.check_for_update(nope)
        self.assertIn("Aucune mise à jour", str(ctx.exception))
        self.assertIn("fonctionne", str(ctx.exception))


class PreferSetupAssetTests(unittest.TestCase):
    def test_installer_is_preferred_over_portable_exe(self):
        from app.services import update_service as us
        data = {"tag_name": "v9.9.9", "html_url": "u", "body": "", "assets": [
            {"name": "GestionCommerciale-v9.9.9.exe", "browser_download_url": "portable"},
            {"name": "GestionCommerciale-Setup-v9.9.9.exe", "browser_download_url": "setup"}]}
        self.assertEqual(us.check_for_update(fetch=lambda _u: data).asset_url, "setup")


if __name__ == "__main__":
    unittest.main()


class SelfUpdateTests(unittest.TestCase):
    def test_commands(self):
        from pathlib import Path
        from app.services import update_service as us
        cmd = us.update_command(Path("C:/t/GestionCommerciale-Setup-v2.exe"), Path("C:/app/GestionCommerciale.exe"), 123)
        self.assertIn("/SILENT", cmd); self.assertIn("/CLOSEAPPLICATIONS", cmd)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            portable = Path(d) / "GestionCommerciale-v2.exe"
            portable.write_bytes(b"x")
            cmd2 = us.update_command(portable, Path("C:/app/GestionCommerciale.exe"), 123)
            self.assertEqual(cmd2[:2], ["cmd", "/c"])
            script = Path(cmd2[2]).read_text(encoding="utf-8")
            self.assertIn("move /Y", script); self.assertIn("start", script); self.assertIn("123", script)

    def test_download_rules(self):
        from unittest import mock
        from app.services import update_service as us
        with self.assertRaises(RuntimeError):
            us.download("http://example.com/x.exe")                  # https obligatoire

        class Resp:
            headers = {"Content-Length": "10"}
            def __init__(self, data): self.data = data
            def read(self, n): d, self.data = self.data[:n], self.data[n:]; return d
            def __enter__(self): return self
            def __exit__(self, *a): return False
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("urllib.request.urlopen", return_value=Resp(b"short")):
                with self.assertRaises(RuntimeError):
                    us.download("https://x/y.exe", directory=Path(d))       # trop petit = incomplet
            with mock.patch("urllib.request.urlopen", return_value=Resp(b"a" * 1_200_000)):
                path = us.download("https://x/GestionCommerciale-Setup-v2.exe", directory=Path(d))
            self.assertTrue(path.is_file()); self.assertTrue(us.is_installer(path))
