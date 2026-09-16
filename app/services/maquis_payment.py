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

FIELD_TENDERED = "tendered"
FIELD_CASH = "cash"
FIELD_MOBILE = "mobile"
FIELD_VOUCHER = "voucher"
FIELD_DEBT = "debt"


@dataclass
class PaymentInput:
    mode: str
    amount_tendered: Optional[float] = None
    cash_amount: float = 0.0
    mobile_money_amount: float = 0.0
    voucher_amount: float = 0.0
    debt_amount: float = 0.0
    tendered_explicit: bool = False


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


def _round_money(v: float) -> float:
    return round(float(v), 2)


def validate(total: float, input: PaymentInput) -> PaymentBreakdown:
    total = _round_money(total)
    if total <= 0:
        raise ValueError("Montant total invalide")
    return _compute(total, input)


def preview_change(total: float, input: PaymentInput) -> float:
    try:
        return validate(total, input).change_amount
    except ValueError:
        return 0.0


def _compute(total: float, input: PaymentInput) -> PaymentBreakdown:
    mode = input.mode
    if mode == MODE_CASH:
        if input.amount_tendered is None:
            raise ValueError("Saisis le montant reçu")
        tendered = _round_money(input.amount_tendered)
        if tendered < total - 0.009:
            raise ValueError(
                f"Montant insuffisant (reçu {tendered:g}, total {total:g})"
            )
        return PaymentBreakdown(
            mode=MODE_CASH,
            total_amount=total,
            cash_amount=total,
            amount_tendered=tendered,
            change_amount=_round_money(tendered - total),
        )
    if mode == MODE_MIXED:
        cash = _round_money(input.cash_amount)
        orange = _round_money(input.mobile_money_amount)
        moov = _round_money(input.voucher_amount)
        debt = _round_money(input.debt_amount)
        paid = cash + orange + moov + debt
        if abs(paid - total) > 0.009:
            raise ValueError(
                f"Le paiement mixte ({paid:g}) doit égaler le total ({total:g})"
            )
        if paid <= 0:
            raise ValueError("Répartis le paiement mixte")
        tendered = input.amount_tendered
        change = 0.0
        amount_tendered = 0.0
        if tendered is not None:
            tendered = _round_money(tendered)
            if cash <= 0:
                raise ValueError("Pas de monnaie sans part espèces")
            if tendered < cash - 0.009:
                raise ValueError("Espèces tendues insuffisantes")
            change = _round_money(tendered - cash)
            amount_tendered = tendered
        return PaymentBreakdown(
            mode=MODE_MIXED,
            total_amount=total,
            cash_amount=cash,
            mobile_amount=orange,
            voucher_amount=moov,
            debt_amount=debt,
            amount_tendered=amount_tendered,
            change_amount=change,
        )
    return _single_mode(total, mode)


def _single_mode(total: float, mode: str) -> PaymentBreakdown:
    mobile = 0.0
    voucher = 0.0
    debt = 0.0
    if mode in (MODE_ORANGE, MODE_WAVE, MODE_CARD, MODE_OTHER):
        mobile = total
    elif mode == MODE_MOOV:
        voucher = total
    elif mode in (MODE_DEBT, config.PAYMENT_METHOD_CREDIT):
        debt = total
        mode = MODE_DEBT
    else:
        mobile = total
    return PaymentBreakdown(
        mode=mode,
        total_amount=total,
        mobile_amount=mobile,
        voucher_amount=voucher,
        debt_amount=debt,
    )


def simple_pay(
    remaining: float,
    mode: str,
    pay_amount: float,
    tendered: Optional[float] = None,
) -> PaymentBreakdown:
    """Paiement partiel sur commande (reste à payer)."""
    remaining = _round_money(remaining)
    pay_amount = _round_money(pay_amount)
    if remaining <= 0:
        raise ValueError("Rien à encaisser")
    if pay_amount <= 0:
        raise ValueError("Montant invalide")
    if pay_amount > remaining + 0.009:
        raise ValueError("Montant supérieur au reste à payer")
    if mode == MODE_CASH:
        t = _round_money(tendered if tendered is not None else pay_amount)
        if t < pay_amount - 0.009:
            raise ValueError("Montant reçu insuffisant")
        return PaymentBreakdown(
            mode=MODE_CASH,
            total_amount=pay_amount,
            cash_amount=pay_amount,
            amount_tendered=t,
            change_amount=_round_money(t - pay_amount),
        )
    br = _single_mode(pay_amount, mode)
    br.total_amount = pay_amount
    return br


def breakdown_to_payment_lines(breakdown: PaymentBreakdown) -> list:
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
        method = MODE_ORANGE if breakdown.mode == MODE_MIXED else breakdown.mode
        if method == MODE_MIXED:
            method = MODE_ORANGE
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
