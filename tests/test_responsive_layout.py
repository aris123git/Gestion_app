"""Tests du moteur responsive (viewport + priorités de colonnes)."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")

from app.ui.responsive import (  # noqa: E402
    PRODUCT_COLUMNS,
    SIDEBAR_DRAWER,
    SIDEBAR_FULL,
    SIDEBAR_ICONS,
    compute_profile,
    visible_column_indexes,
)
from app.ui.responsive.table_manager import ColumnSpec  # noqa: E402


class ResponsiveViewportTestCase(unittest.TestCase):
    def test_width_modes(self) -> None:
        self.assertEqual(compute_profile(640, 800).width_mode, "mobile")
        self.assertEqual(compute_profile(900, 800).width_mode, "compact")
        self.assertEqual(compute_profile(1200, 800).width_mode, "desktop")
        self.assertEqual(compute_profile(1600, 900).width_mode, "large")

    def test_height_modes_independent_of_width(self) -> None:
        wide_short = compute_profile(1920, 600)
        wide_tall = compute_profile(1920, 1080)
        self.assertEqual(wide_short.width_mode, wide_tall.width_mode)
        self.assertEqual(wide_short.height_mode, "short")
        self.assertEqual(wide_tall.height_mode, "tall")
        self.assertNotEqual(wide_short.density, wide_tall.density)

    def test_sidebar_modes(self) -> None:
        self.assertEqual(compute_profile(640, 800).sidebar_mode, SIDEBAR_DRAWER)
        self.assertEqual(compute_profile(900, 800).sidebar_mode, SIDEBAR_ICONS)
        self.assertEqual(compute_profile(1400, 900).sidebar_mode, SIDEBAR_FULL)

    def test_card_columns_scale(self) -> None:
        self.assertEqual(compute_profile(640, 800).card_columns, 1)
        self.assertLessEqual(compute_profile(900, 800).card_columns, 2)
        self.assertGreaterEqual(compute_profile(1600, 1000).card_columns, 3)


class TablePriorityTestCase(unittest.TestCase):
    def test_priority_keeps_essentials_first(self) -> None:
        # Budget juste pour priorité 1 des produits (name+sale+stock ≈ 340).
        visible = visible_column_indexes(PRODUCT_COLUMNS, 360)
        keys = [PRODUCT_COLUMNS[i].key for i in visible]
        self.assertIn("name", keys)
        self.assertIn("sale_price", keys)
        self.assertIn("stock", keys)
        self.assertNotIn("barcode", keys)

    def test_more_space_reveals_secondary(self) -> None:
        narrow = set(visible_column_indexes(PRODUCT_COLUMNS, 360))
        wide = set(visible_column_indexes(PRODUCT_COLUMNS, 900))
        self.assertTrue(narrow.issubset(wide))
        self.assertGreater(len(wide), len(narrow))

    def test_greedy_partial_priority_group(self) -> None:
        cols = (
            ColumnSpec("a", 1, 100, stretch=True),
            ColumnSpec("b", 2, 100),
            ColumnSpec("c", 2, 100),
            ColumnSpec("d", 3, 100),
        )
        # 100 (a) + 100 (b) = 200 ; c ne rentre pas.
        visible = visible_column_indexes(cols, 220)
        keys = [cols[i].key for i in visible]
        self.assertEqual(keys, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
