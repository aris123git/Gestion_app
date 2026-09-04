"""Tests logos par type de commerce."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.printers.shop_logos import (
    LOGOS_DIR,
    default_logo_path,
    list_default_logos,
    resolve_logo_path,
    shop_type_slug,
)


class ShopLogosTestCase(unittest.TestCase):
    def test_all_types_have_files(self) -> None:
        logos = list_default_logos()
        self.assertGreaterEqual(len(logos), 9)
        for label, path in logos:
            self.assertTrue(path.is_file(), msg=f"{label}: {path}")
            self.assertEqual(path.suffix, ".png")

    def test_slug_mapping(self) -> None:
        self.assertEqual(shop_type_slug("Poissonnerie"), "poissonnerie")
        self.assertEqual(shop_type_slug("Magasin d'électronique"), "electronique")
        self.assertEqual(shop_type_slug("Inconnu"), "autre")

    def test_resolve_prefers_custom(self) -> None:
        custom = default_logo_path("Pharmacie")
        assert custom is not None
        # Custom file exists → used
        got = resolve_logo_path(
            logo_path=str(custom), shop_type="Poissonnerie"
        )
        self.assertEqual(Path(got).name, "pharmacie.png")

    def test_resolve_fallback_type(self) -> None:
        got = resolve_logo_path(logo_path="", shop_type="Quincaillerie")
        self.assertTrue(got.endswith("quincaillerie.png"))
        self.assertTrue(Path(got).is_file())

    def test_resolve_missing_custom_falls_back(self) -> None:
        got = resolve_logo_path(
            logo_path="/tmp/does_not_exist_logo.png",
            shop_type="Boulangerie",
        )
        self.assertTrue(got.endswith("boulangerie.png"))

    def test_prefer_default(self) -> None:
        pharma = default_logo_path("Pharmacie")
        fish = default_logo_path("Poissonnerie")
        assert pharma and fish
        got = resolve_logo_path(
            logo_path=str(pharma),
            shop_type="Poissonnerie",
            prefer_default=True,
        )
        self.assertEqual(Path(got).name, "poissonnerie.png")

    def test_logos_dir(self) -> None:
        self.assertTrue(LOGOS_DIR.is_dir())


if __name__ == "__main__":
    unittest.main()
