"""Tests calcul paiement Maquis (parité PaymentCalculator mobile)."""

import unittest

from app.services.maquis_payment import (
    MODE_CASH,
    MODE_MIXED,
    MODE_ORANGE,
    PaymentInput,
    preview_change,
    simple_pay,
    validate,
)


class MaquisPaymentTestCase(unittest.TestCase):
    def test_cash_exact(self) -> None:
        br = validate(1000, PaymentInput(mode=MODE_CASH, amount_tendered=1000))
        self.assertEqual(br.change_amount, 0)
        self.assertEqual(br.cash_amount, 1000)

    def test_cash_overpay(self) -> None:
        br = validate(1000, PaymentInput(mode=MODE_CASH, amount_tendered=2000))
        self.assertEqual(br.change_amount, 1000)

    def test_cash_underpay_fails(self) -> None:
        with self.assertRaises(ValueError):
            validate(1000, PaymentInput(mode=MODE_CASH, amount_tendered=500))

    def test_orange_full(self) -> None:
        br = validate(1500, PaymentInput(mode=MODE_ORANGE))
        self.assertEqual(br.mobile_amount, 1500)

    def test_mixed_balanced(self) -> None:
        br = validate(
            1000,
            PaymentInput(
                mode=MODE_MIXED,
                cash_amount=500,
                mobile_money_amount=500,
            ),
        )
        self.assertEqual(br.total_amount, 1000)

    def test_mixed_mismatch_fails(self) -> None:
        with self.assertRaises(ValueError):
            validate(
                1000,
                PaymentInput(mode=MODE_MIXED, cash_amount=400, mobile_money_amount=500),
            )

    def test_mixed_change(self) -> None:
        br = validate(
            1000,
            PaymentInput(
                mode=MODE_MIXED,
                cash_amount=500,
                mobile_money_amount=500,
                amount_tendered=1000,
            ),
        )
        self.assertEqual(br.change_amount, 500)

    def test_preview_invalid_zero(self) -> None:
        self.assertEqual(
            preview_change(1000, PaymentInput(mode=MODE_CASH, amount_tendered=100)),
            0,
        )

    def test_simple_partial_cash(self) -> None:
        br = simple_pay(5000, MODE_CASH, 2000, 2000)
        self.assertEqual(br.total_amount, 2000)


if __name__ == "__main__":
    unittest.main()
