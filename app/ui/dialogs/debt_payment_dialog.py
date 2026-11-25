"""Dialogue de remboursement de dette client."""
from __future__ import annotations
from app.i18n import t
from typing import Optional
from PySide6.QtWidgets import QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout
from app import config
from app.services import settings_service
from app.ui.widgets.helpers import dialog_header_banner, warn
from app.utils.helpers import format_money
from app.ui.widgets.money_spin import MoneySpinBox

class DebtPaymentDialog(QDialog):
    """Saisie d'un remboursement (montant, mode, note)."""

    def __init__(self, client_name: str, balance: float, parent=None, max_amount: Optional[float]=None):
        super().__init__(parent)
        self.setWindowTitle(t('Régler une dette'))
        self.setModal(True)
        self.setMinimumWidth(420)
        self.result_data: Optional[dict] = None
        ceiling = float(max_amount if max_amount is not None else balance)
        currency = settings_service.get_currency()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(dialog_header_banner(client_name, f"{t('Solde dû')} : {format_money(balance, currency)}", background='#b45309'))
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        outer.addLayout(layout, 1)
        card = QFrame()
        card.setObjectName('Card')
        form = QFormLayout(card)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)
        self.amount = MoneySpinBox()
        self.amount.setRange(0, max(ceiling, 0))
        self.amount.setDecimals(3)
        self.amount.setValue(ceiling if ceiling > 0 else 0)
        self.method = QComboBox()
        self.method.addItems(config.PAYMENT_METHODS)
        self.note = QLineEdit()
        self.note.setPlaceholderText(t('Facultatif'))
        form.addRow(t('Montant'), self.amount)
        form.addRow(t('Mode de paiement'), self.method)
        form.addRow(t('Note'), self.note)
        layout.addWidget(card)
        buttons = QHBoxLayout()
        pay_all = QPushButton(t('Tout régler'))
        pay_all.clicked.connect(lambda: self.amount.setValue(ceiling))
        cancel = QPushButton(t('Annuler'))
        cancel.clicked.connect(self.reject)
        save = QPushButton(t('Enregistrer'))
        save.setObjectName('Primary')
        save.clicked.connect(self._save)
        buttons.addWidget(pay_all)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        if self.amount.value() <= 0:
            warn(self, t('Indiquez un montant supérieur à zéro.'))
            return
        self.result_data = {'amount': self.amount.value(), 'payment_method': self.method.currentText(), 'note': self.note.text().strip()}
        self.accept()
