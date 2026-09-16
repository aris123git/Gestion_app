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


if __name__ == "__main__":
    unittest.main()
