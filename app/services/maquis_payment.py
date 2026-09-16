"""Calcul paiement Maquis — aligné sur PaymentCalculator (app mobile)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app import config

MODE_CASH = "Espèces"
MODE_ORANGE = "Orange Money"
MODE_MOOV = "Moov Money"
MODE_WAVE = "Wave"
MODE_CARD = "Carte bancaire"
MODE_OTHER = "Autre"
MODE_DEBT = "Dette"
MODE_MIXED = "Mixte"

PAYMENT_CHOICES = (
    MODE_CASH,
    MODE_ORANGE,
    MODE_MOOV,
    MODE_WAVE,
    MODE_CARD,
    MODE_OTHER,
    MODE_MIXED,
)


@dataclass
class PaymentBreakdown:
    mode: str
    total_amount: float
    cash_amount: float = 0.0
    mobile_amount: float = 0.0
    voucher_amount: float = 0.0
    debt_amount: float = 0.0
    amount_tendered: float = 0.0
    change_amount: float = 0.0


def simple_pay(
    remaining: float,
    mode: str,
    pay_amount: float,
    tendered: Optional[float] = None,
) -> PaymentBreakdown:
    remaining = round(float(remaining), 2)
    pay_amount = round(float(pay_amount), 2)
    if remaining <= 0:
        raise ValueError("Rien à encaisser")
    if pay_amount <= 0:
        raise ValueError("Montant invalide")
    if pay_amount > remaining + 0.009:
        raise ValueError("Montant supérieur au reste à payer")
    change = 0.0
    amount_tendered = 0.0
    if mode == MODE_CASH:
        t = round(float(tendered if tendered is not None else pay_amount), 2)
        if t < pay_amount - 0.009:
            raise ValueError("Montant reçu insuffisant")
        change = round(t - pay_amount, 2)
        amount_tendered = t
    cash = pay_amount if mode == MODE_CASH else 0.0
    mobile = pay_amount if mode in (MODE_ORANGE, MODE_WAVE, MODE_CARD, MODE_OTHER) else 0.0
    voucher = pay_amount if mode == MODE_MOOV else 0.0
    debt = pay_amount if mode in (MODE_DEBT, config.PAYMENT_METHOD_CREDIT) else 0.0
    return PaymentBreakdown(
        mode=mode,
        total_amount=pay_amount,
        cash_amount=cash,
        mobile_amount=mobile,
        voucher_amount=voucher,
        debt_amount=debt,
        amount_tendered=amount_tendered,
        change_amount=change,
    )


def breakdown_to_payment_lines(breakdown: PaymentBreakdown) -> list:
    """Convertit un breakdown en lignes compatibles OpenOrderPayment / caisse."""
    from app.controllers.sale_controller import PaymentLine

    lines: list[PaymentLine] = []
    if breakdown.cash_amount > 0:
        lines.append(
            PaymentLine(
                method=MODE_CASH,
                amount=breakdown.cash_amount,
                amount_tendered=breakdown.amount_tendered or breakdown.cash_amount,
            )
        )
    if breakdown.mobile_amount > 0:
        method = breakdown.mode if breakdown.mode != MODE_MIXED else MODE_ORANGE
        lines.append(PaymentLine(method=method, amount=breakdown.mobile_amount))
    if breakdown.voucher_amount > 0:
        lines.append(PaymentLine(method=MODE_MOOV, amount=breakdown.voucher_amount))
    if breakdown.debt_amount > 0:
        lines.append(
            PaymentLine(method=config.PAYMENT_METHOD_CREDIT, amount=breakdown.debt_amount)
        )
    if not lines and breakdown.total_amount > 0:
        lines.append(PaymentLine(method=breakdown.mode, amount=breakdown.total_amount))
    return lines
