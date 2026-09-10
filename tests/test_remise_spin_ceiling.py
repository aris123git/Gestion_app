"""La remise caisse ne doit pas ouvrir de dialogue à chaque clic des flèches."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

_DATA_DIR = tempfile.mkdtemp(prefix="remise_spin_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDoubleSpinBox  # noqa: E402

from app import config  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.services import cash_controls, permissions as perms  # noqa: E402


class RemiseSpinCeilingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_database()
        seed_all()
        cash_controls.set_limits(10, 5_000)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def test_spin_stops_at_ceiling_without_popup_logic(self) -> None:
        cashier = SimpleNamespace(role=perms.ROLE_CASHIER)
        spin = QDoubleSpinBox()
        spin.setDecimals(0)
        spin.setSingleStep(100)
        spin.setRange(0, 0)

        def apply_ceiling(subtotal: float) -> float:
            capped = cash_controls.max_discount_amount(subtotal, cashier)
            ceiling = max(
                0.0,
                subtotal if capped is None else min(subtotal, float(capped)),
            )
            spin.blockSignals(True)
            spin.setMaximum(ceiling)
            if spin.value() > ceiling:
                spin.setValue(ceiling)
            spin.blockSignals(False)
            return ceiling

        self.assertEqual(apply_ceiling(0), 0)
        spin.stepBy(1)
        self.assertEqual(spin.value(), 0)

        self.assertEqual(apply_ceiling(10_000), 1_000)
        spin.setValue(0)
        for _ in range(15):
            spin.stepBy(1)
        self.assertEqual(spin.value(), 1_000)
        spin.stepBy(1)
        self.assertEqual(spin.value(), 1_000)


if __name__ == "__main__":
    unittest.main()
