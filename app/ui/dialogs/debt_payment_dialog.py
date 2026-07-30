"""Dialogue de remboursement de dette client."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app import config
from app.services import settings_service
from app.ui.widgets.helpers import warn
from app.utils.helpers import format_money


class DebtPaymentDialog(QDialog):
    """Saisie d'un remboursement (montant, mode, note)."""

    def __init__(
        self,
        client_name: str,
        balance: float,
        parent=None,
        max_amount: Optional[float] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Régler une dette")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.result_data: Optional[dict] = None
        ceiling = float(max_amount if max_amount is not None else balance)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        currency = settings_service.get_currency()
        info = QLabel(
            f"<b>{client_name}</b><br/>"
            f"Solde dû : {format_money(balance, currency)}"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, max(ceiling, 0))
        self.amount.setDecimals(0)
        self.amount.setValue(ceiling if ceiling > 0 else 0)
        self.method = QComboBox()
        self.method.addItems(config.PAYMENT_METHODS)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Facultatif")
        form.addRow("Montant", self.amount)
        form.addRow("Mode de paiement", self.method)
        form.addRow("Note", self.note)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        pay_all = QPushButton("Tout régler")
        pay_all.clicked.connect(lambda: self.amount.setValue(ceiling))
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Enregistrer")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        buttons.addWidget(pay_all)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        if self.amount.value() <= 0:
            warn(self, "Indiquez un montant supérieur à zéro.")
            return
        self.result_data = {
            "amount": self.amount.value(),
            "payment_method": self.method.currentText(),
            "note": self.note.text().strip(),
        }
        self.accept()
