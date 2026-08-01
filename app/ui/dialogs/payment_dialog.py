"""Dialogue de paiement : modes multiples, monnaie rendue, paiement mixte, dette."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
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
        self.allow_credit = bool(allow_credit)
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
            spin = self._make_spin()
            self.method_inputs[method] = spin
            form.addRow(method, spin)

        # Dette : visible uniquement si un client est sélectionné en caisse.
        self.credit_method = config.PAYMENT_METHOD_CREDIT
        self.credit_input: QDoubleSpinBox | None = None
        if self.allow_credit:
            self.credit_input = self._make_spin()
            self.method_inputs[self.credit_method] = self.credit_input
            form.addRow(self.credit_method, self.credit_input)
            credit_hint = QLabel(
                "Choisissez « Dette » pour porter le montant sur le compte client "
                "(au lieu d'espèces ou d'un autre mode)."
            )
            credit_hint.setWordWrap(True)
            credit_hint.setStyleSheet("color: #b45309; font-size: 12px;")
            form.addRow("", credit_hint)

        layout.addWidget(methods_card)

        quick_row = QHBoxLayout()
        quick_cash = QPushButton("Payer le total en espèces")
        quick_cash.clicked.connect(self._pay_all_cash)
        quick_row.addWidget(quick_cash)
        if self.allow_credit:
            quick_debt = QPushButton("Mettre tout en dette")
            quick_debt.setObjectName("Primary")
            quick_debt.clicked.connect(self._pay_all_credit)
            quick_row.addWidget(quick_debt)
        layout.addLayout(quick_row)

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

        if not self.allow_credit:
            no_client = QLabel(
                "Sélectionnez un client en caisse pour pouvoir encaisser en dette."
            )
            no_client.setWordWrap(True)
            no_client.setStyleSheet("color: #64748b; font-size: 12px;")
            layout.addWidget(no_client)

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

    def _make_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 1_000_000_000)
        spin.setDecimals(0)
        spin.setSingleStep(500)
        spin.setSuffix(f" {self.currency}")
        spin.valueChanged.connect(self._recalculate)
        return spin

    # --- Calculs -----------------------------------------------------------
    def _credit_amount(self) -> float:
        if self.credit_input is None:
            return 0.0
        return float(self.credit_input.value())

    def _cash_paid_total(self) -> float:
        """Montants réellement encaissés (hors dette)."""
        total = 0.0
        for method, spin in self.method_inputs.items():
            if method == self.credit_method:
                continue
            total += float(spin.value())
        return total

    def _covered_total(self) -> float:
        return self._cash_paid_total() + self._credit_amount()

    def _pay_all_cash(self) -> None:
        for method, spin in self.method_inputs.items():
            spin.blockSignals(True)
            spin.setValue(self.total if method == "Espèces" else 0)
            spin.blockSignals(False)
        self.received_input.setValue(self.total)
        self._recalculate()

    def _pay_all_credit(self) -> None:
        if self.credit_input is None:
            return
        for method, spin in self.method_inputs.items():
            spin.blockSignals(True)
            spin.setValue(self.total if method == self.credit_method else 0)
            spin.blockSignals(False)
        self.received_input.setValue(0)
        self._recalculate()

    def _recalculate(self) -> None:
        cash_paid = self._cash_paid_total()
        credit = self._credit_amount()
        covered = cash_paid + credit
        received = self.received_input.value()
        change = max(0.0, received - self.total)
        remaining = max(0.0, self.total - covered)

        parts = [
            f"Encaissé : {format_money(cash_paid, self.currency)}",
            f"Monnaie à rendre : {format_money(change, self.currency)}",
        ]
        if credit > 0:
            parts.append(
                f"<span style='color:#f59e0b;'>Dette client : "
                f"{format_money(credit, self.currency)}</span>"
            )
        if remaining > 0:
            parts.append(
                f"<span style='color:#dc2626;'>Montant insuffisant "
                f"({format_money(remaining, self.currency)} manquant)</span>"
            )
        elif credit > 0 and cash_paid <= 0:
            parts.append(
                "<span style='color:#f59e0b;'>Vente entièrement portée en dette</span>"
            )
        else:
            parts.append("<span style='color:#16a34a;'>Paiement suffisant</span>")
        self.summary.setText("<br>".join(parts))

        self.validate.setEnabled(covered >= self.total)

    def _confirm(self) -> None:
        cash_paid = self._cash_paid_total()
        credit = self._credit_amount()
        if cash_paid + credit < self.total:
            return
        self.result_payments = [
            PaymentLine(method=method, amount=spin.value())
            for method, spin in self.method_inputs.items()
            if spin.value() > 0
        ]
        # Si l'argent reçu n'a pas été saisi, on suppose le total encaissé (hors dette).
        self.amount_received = self.received_input.value() or cash_paid
        self.change_due = max(0.0, self.amount_received - self.total)
        self.use_credit = credit > 0
        self.accept()
