"""Tests association / sync portail web."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_portal_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import portal_service, settings_service  # noqa: E402


class PortalAssociationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cls.portal_data = Path(tempfile.mkdtemp(prefix="nexapos_portal_data_"))
        os.environ["NEXAPOS_PORTAL_DATA"] = str(cls.portal_data)
        os.environ["NEXAPOS_PORTAL_PORT"] = "18787"
        os.environ["NEXAPOS_PORTAL_HOST"] = "127.0.0.1"
        # Recharger le module portail avec le bon DATA_DIR.
        import importlib

        import portal.__main__ as portal_main

        importlib.reload(portal_main)
        cls.portal_main = portal_main
        cls.server = portal_main.ThreadingHTTPServer(
            ("127.0.0.1", 18787), portal_main.PortalHandler
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)
        shutil.rmtree(cls.portal_data, ignore_errors=True)

    def setUp(self) -> None:
        settings_service.set_setting(portal_service.SETTING_ENABLED, "0")
        settings_service.set_setting(portal_service.SETTING_ASSOCIATED, "0")
        settings_service.set_setting(portal_service.SETTING_ENTERPRISE_ID, "")
        settings_service.set_setting(portal_service.SETTING_API_KEY, "")
        settings_service.set_setting(portal_service.SETTING_LAST_SYNC, "")
        settings_service.set_setting(portal_service.SETTING_LAST_ERROR, "")
        settings_service.set_setting(
            portal_service.SETTING_URL, "http://127.0.0.1:18787"
        )

    def test_ensure_credentials(self) -> None:
        eid, key = portal_service.ensure_credentials()
        self.assertTrue(eid.startswith("ENT-"))
        self.assertGreaterEqual(len(key), 20)
        eid2, key2 = portal_service.ensure_credentials()
        self.assertEqual(eid, eid2)
        self.assertEqual(key, key2)

    def test_health(self) -> None:
        portal_service.save_portal_settings(
            enabled=True, url="http://127.0.0.1:18787"
        )
        result = portal_service.test_connection()
        self.assertTrue(result.ok, result.message)

    def test_associate_and_sync(self) -> None:
        portal_service.save_portal_settings(
            enabled=True,
            url="http://127.0.0.1:18787",
            owner_email="boss@example.com",
        )
        eid, key = portal_service.ensure_credentials()
        assoc = portal_service.associate()
        self.assertTrue(assoc.ok, assoc.message)
        self.assertTrue(portal_service.is_associated())
        sync = portal_service.sync_now()
        self.assertTrue(sync.ok, sync.message)
        self.assertTrue(portal_service.get_last_sync())

        record = self.portal_main._load(eid)
        self.assertIsNotNone(record)
        self.assertEqual(record["api_key_hash"], self.portal_main._hash_key(key))
        self.assertIn("metrics", record.get("snapshot") or {})
        self.assertIn("revenue_today", (record["snapshot"].get("metrics") or {}))

    def test_sync_rejects_bad_key(self) -> None:
        portal_service.save_portal_settings(
            enabled=True, url="http://127.0.0.1:18787"
        )
        portal_service.ensure_credentials()
        self.assertTrue(portal_service.associate().ok)
        settings_service.set_setting(portal_service.SETTING_API_KEY, "wrong-key")
        bad = portal_service.sync_now()
        # associate may succeed again with wrong key re-registering — sync uses auth
        # After regenerate path: force associated + wrong key without re-associate
        settings_service.set_setting(portal_service.SETTING_ASSOCIATED, "1")
        settings_service.set_setting(portal_service.SETTING_API_KEY, "totally-wrong")
        bad = portal_service._request(
            "POST",
            "/api/v1/sync",
            {
                "enterprise_id": portal_service.get_enterprise_id(),
                "snapshot": {"shop": {}, "metrics": {}},
            },
            auth=True,
        )
        self.assertFalse(bad.ok)


if __name__ == "__main__":
    unittest.main()
