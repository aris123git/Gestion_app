"""Tests persistance panier Maquis (format CartJson)."""

import unittest

from app.controllers.sale_controller import CartLine
from app.services.maquis_cart_json import decode_cart, encode_cart


class MaquisCartJsonTestCase(unittest.TestCase):
    def test_roundtrip(self) -> None:
        lines = [
            CartLine(
                product_id=3,
                name="Dinde",
                unit_price=2500.0,
                quantity=2.0,
                purchase_price=1200.0,
            )
        ]
        raw = encode_cart(lines)
        back = decode_cart(raw)
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0].product_id, 3)
        self.assertEqual(back[0].quantity, 2.0)
        self.assertEqual(back[0].unit_price, 2500.0)
        self.assertFalse(back[0].free_amount)

    def test_free_amount_roundtrip(self) -> None:
        lines = [
            CartLine(
                product_id=7,
                name="Poisson — 300",
                unit_price=1500.0,
                quantity=0.2,
                purchase_price=1000.0,
                free_amount=True,
                amount=300.0,
            )
        ]
        raw = encode_cart(lines)
        self.assertIn("|1|", raw)
        back = decode_cart(raw)
        self.assertEqual(len(back), 1)
        self.assertTrue(back[0].free_amount)
        self.assertEqual(back[0].product_id, 7)
        self.assertAlmostEqual(back[0].quantity, 0.2)

    def test_loyalty_skipped(self) -> None:
        lines = [
            CartLine(
                product_id=1,
                name="Offert",
                unit_price=500.0,
                quantity=1.0,
                purchase_price=0.0,
                loyalty_reward=True,
            )
        ]
        self.assertEqual(encode_cart(lines), "")


if __name__ == "__main__":
    unittest.main()
