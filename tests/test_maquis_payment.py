"""Tests calcul paiement Maquis (parité mobile)."""

import unittest

from app.services.maquis_payment import MODE_CASH, simple_pay


class MaquisPaymentTestCase(unittest.TestCase):
    def test_cash_change(self) -> None:
        br = simple_pay(1000, MODE_CASH, 1000, 1500)
        self.assertEqual(br.total_amount, 1000)
        self.assertEqual(br.change_amount, 500)

    def test_partial(self) -> None:
        br = simple_pay(5000, MODE_CASH, 2000, 2000)
        self.assertEqual(br.total_amount, 2000)


if __name__ == "__main__":
    unittest.main()
