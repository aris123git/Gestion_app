"""Champ montant : jusqu'à 3 décimales, sans zéros inutiles (1250 / 1250,5 / 0,125)."""

from __future__ import annotations

from PySide6.QtWidgets import QDoubleSpinBox

MONEY_DECIMALS = 3


class MoneySpinBox(QDoubleSpinBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDecimals(MONEY_DECIMALS)

    def textFromValue(self, value: float) -> str:  # noqa: N802 (API Qt)
        text = super().textFromValue(value)
        point = self.locale().decimalPoint()
        if point in text:
            text = text.rstrip("0").rstrip(point)
        return text
