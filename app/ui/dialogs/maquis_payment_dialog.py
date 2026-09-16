"""Paiement commande Maquis — modes et montant (parité mobile)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from app import config
from app.i18n import t
from app.services.maquis_payment import PAYMENT_CHOICES, PaymentBreakdown, simple_pay
from app.ui.widgets.client_search import ClientSearchField


class MaquisPaymentDialog(QDialog):
    """Encaissement commande : mode + montant (+ client si dette)."""

    def __init__(
        self,
        remaining: float,
        *,
        pay_full: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.remaining = float(remaining)
        self.breakdown: Optional[PaymentBreakdown] = None
        self.debt_client_id: Optional[int] = None
        self.setWindowTitle(t("Paiement"))
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"{t('Reste à payer')} : {remaining:g}"
                if not pay_full
                else f"{t('Total')} : {remaining:g}"
            )
        )
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(list(PAYMENT_CHOICES) + [t("Dette")])
        form.addRow(t("Mode"), self.mode)
        self.amount = QDoubleSpinBox()
        self.amount.setMaximum(max(remaining, 0.01) * 100)
        self.amount.setDecimals(0)
        self.amount.setValue(remaining if pay_full else 0)
        self.amount.setEnabled(not pay_full)
        form.addRow(t("Montant"), self.amount)
        self.tendered = QDoubleSpinBox()
        self.tendered.setMaximum(1e12)
        self.tendered.setDecimals(0)
        self.tendered.setValue(remaining)
        form.addRow(t("Montant reçu"), self.tendered)
        self.client_search = ClientSearchField()
        form.addRow(t("Client (dette)"), self.client_search)
        layout.addLayout(form)
        self.partial_debt = QLabel("")
        self.partial_debt.setWordWrap(True)
        layout.addWidget(self.partial_debt)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._confirm)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _confirm(self) -> None:
        mode = self.mode.currentText()
        if mode == t("Dette"):
            mode = config.PAYMENT_METHOD_CREDIT
        pay = float(self.amount.value())
        tendered = float(self.tendered.value())
        try:
            self.breakdown = simple_pay(self.remaining, mode, pay, tendered)
        except ValueError as exc:
            self.partial_debt.setText(str(exc))
            return
        if mode == config.PAYMENT_METHOD_CREDIT:
            self.debt_client_id = self.client_search.client_id
            if not self.debt_client_id:
                self.partial_debt.setText(t("Sélectionnez un client pour la dette."))
                return
        self.accept()
