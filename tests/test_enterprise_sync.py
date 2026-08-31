"""Tests Lot 1 multi-magasins : export / import / classement."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


class EnterpriseSyncTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["GESTION_DATA_DIR"] = self._tmpdir.name
        # Recharge les modules app pour prendre le nouveau DATA_DIR.
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]

        from app.database.connection import init_database, session_scope
        from app.database.seed import seed_all
        from app.models.settings import ShopInfo

        init_database()
        seed_all()
        with session_scope() as session:
            shop = session.get(ShopInfo, 1)
            shop.is_configured = True
            shop.name = "Magasin Test A"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_export_import_ranking(self) -> None:
        from app.services import enterprise_sync_service as sync
        from app.services import settings_service

        share = Path(self._tmpdir.name) / "share"
        share.mkdir()
        settings_service.set_setting(sync.SETTING_SHARE_PATH, str(share))
        settings_service.set_setting(sync.SETTING_SHOP_CODE, "MAG-A")

        result = sync.export_day_to_share(date.today())
        self.assertTrue(result.ok, result.message)
        files = list(share.glob("*.json"))
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["shop_code"], "MAG-A")
        self.assertIn("cash_revenue", payload["metrics"])

        other = {
            "schema": 1,
            "shop_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "shop_code": "MAG-B",
            "shop_name": "Magasin B",
            "currency": "FCFA",
            "period": "day",
            "date": date.today().isoformat(),
            "exported_at": "2026-08-31T12:00:00",
            "metrics": {
                "cash_revenue": 50000,
                "profit_gross": 20000,
                "profit_net": 15000,
                "expenses": 5000,
                "sales_count": 12,
                "client_debts": 3000,
                "client_debts_count": 2,
                "debt_repayments": 0,
                "treasury": 45000,
            },
        }
        (share / "mag-b.json").write_text(json.dumps(other), encoding="utf-8")

        imported = sync.scan_and_import(share)
        self.assertTrue(imported.ok)
        self.assertGreaterEqual(imported.count, 2)

        ranking = sync.ranking_for_day(date.today())
        self.assertGreaterEqual(len(ranking), 2)
        self.assertEqual(ranking[0].shop_code, "MAG-B")
        totals = sync.consolidated_for_day(date.today())
        self.assertGreaterEqual(totals["cash_revenue"], 50000)
        self.assertGreaterEqual(totals["shop_count"], 2)

        detail = sync.shop_detail(other["shop_id"], date.today())
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.shop_name, "Magasin B")


if __name__ == "__main__":
    unittest.main()
