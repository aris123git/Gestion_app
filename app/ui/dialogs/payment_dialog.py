"""Dialogue de paiement : modes multiples, monnaie rendue, paiement mixte."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app import config
from app.controllers.sale_controller import PaymentLine
from app.services import settings_service
from app.utils.helpers import format_money


class PaymentDialog(QDialog):
    """Recueille les paiements (éventuellement mixtes) pour une vente."""

    def __init__(self, total: float, allow_credit: bool = False, parent=None):
        super().__init__(parent)
        self.total = float(total)
        self.currency = settings_service.get_currency()
        self.setWindowTitle("Paiement")
        self.setModal(True)
        self.setMinimumWidth(460)

        self.result_payments: List[PaymentLine] = []
        self.amount_received = 0.0
        self.change_due = 0.0
        self.use_credit = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header = QLabel(f"Total à payer : {format_money(self.total, self.currency)}")
        header.setObjectName("PageTitle")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        hint = QLabel("Saisissez un ou plusieurs modes de paiement (paiement mixte).")
        hint.setStyleSheet("color: #64748b;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        methods_card = QFrame()
        methods_card.setObjectName("Card")
        form = QFormLayout(methods_card)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)

        self.method_inputs = {}
        for method in config.PAYMENT_METHODS:
            spin = QDoubleSpinBox()
            spin.setRange(0, 1_000_000_000)
            spin.setDecimals(0)
            spin.setSingleStep(500)
            spin.setSuffix(f" {self.currency}")
            spin.valueChanged.connect(self._recalculate)
            self.method_inputs[method] = spin
            form.addRow(method, spin)
        layout.addWidget(methods_card)

        # Bouton pratique : régler tout en espèces.
        quick = QPushButton("Payer le total en espèces")
        quick.clicked.connect(self._pay_all_cash)
        layout.addWidget(quick)

        received_row = QFormLayout()
        self.received_input = QDoubleSpinBox()
        self.received_input.setRange(0, 1_000_000_000)
        self.received_input.setDecimals(0)
        self.received_input.setSingleStep(500)
        self.received_input.setSuffix(f" {self.currency}")
        self.received_input.valueChanged.connect(self._recalculate)
        received_row.addRow("Argent reçu (espèces)", self.received_input)
        layout.addLayout(received_row)

        self.summary = QLabel()
        self.summary.setStyleSheet("font-size: 15px;")
        layout.addWidget(self.summary)

        self.credit_check = QCheckBox("Porter le reste à la dette du client")
        self.credit_check.setVisible(allow_credit)
        self.credit_check.stateChanged.connect(self._recalculate)
        layout.addWidget(self.credit_check)

        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        self.validate = QPushButton("Valider le paiement")
        self.validate.setObjectName("Success")
        self.validate.clicked.connect(self._confirm)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(self.validate)
        layout.addLayout(buttons)

        self._recalculate()

    # --- Calculs -----------------------------------------------------------
    def _paid_total(self) -> float:
        return sum(spin.value() for spin in self.method_inputs.values())

    def _pay_all_cash(self) -> None:
        self.method_inputs["Espèces"].setValue(self.total)
        self.received_input.setValue(self.total)

    def _recalculate(self) -> None:
        paid = self._paid_total()
        received = self.received_input.value()
        change = max(0.0, received - self.total)
        remaining = max(0.0, self.total - paid)

        credit = self.credit_check.isChecked() and self.credit_check.isVisible()
        parts = [
            f"Payé : {format_money(paid, self.currency)}",
            f"Monnaie à rendre : {format_money(change, self.currency)}",
        ]
        if remaining > 0 and not credit:
            parts.append(
                f"<span style='color:#dc2626;'>Montant insuffisant "
                f"({format_money(remaining, self.currency)} manquant)</span>"
            )
        elif remaining > 0 and credit:
            parts.append(
                f"<span style='color:#f59e0b;'>Dette client : "
                f"{format_money(remaining, self.currency)}</span>"
            )
        else:
            parts.append("<span style='color:#16a34a;'>Paiement suffisant</span>")
        self.summary.setText("<br>".join(parts))

        self.validate.setEnabled(paid >= self.total or credit)

    def _confirm(self) -> None:
        paid = self._paid_total()
        credit = self.credit_check.isChecked() and self.credit_check.isVisible()
        if paid < self.total and not credit:
            return
        self.result_payments = [
            PaymentLine(method=method, amount=spin.value())
            for method, spin in self.method_inputs.items()
            if spin.value() > 0
        ]
        # Si l'argent reçu n'a pas été saisi, on suppose le total en espèces.
        self.amount_received = self.received_input.value() or paid
        self.change_due = max(0.0, self.amount_received - self.total)
        self.use_credit = credit
        self.accept()
