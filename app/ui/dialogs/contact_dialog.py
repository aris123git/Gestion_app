"""Dialogue générique pour un contact (client ou fournisseur)."""
from __future__ import annotations
from app.i18n import t
from typing import Optional
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCheckBox, QDateEdit, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout
from app.ui.widgets.helpers import warn

class ContactDialog(QDialog):
    """Formulaire nom/téléphone/adresse/email (+ dette pour les clients)."""

    def __init__(self, title: str, contact=None, with_debt: bool=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)
        self.with_debt = with_debt
        self.data: Optional[dict] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.phone2 = QLineEdit()
        self.address = QLineEdit()
        self.email = QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(70)
        form.addRow(t('Nom'), self.name)
        form.addRow(t('Téléphone'), self.phone)
        form.addRow(t('Téléphone 2'), self.phone2)
        form.addRow(t('Adresse'), self.address)
        form.addRow(t('Email'), self.email)
        if with_debt:
            self.debt = QDoubleSpinBox()
            self.debt.setRange(0, 1000000000)
            self.debt.setDecimals(0)
            label = "Solde d'ouverture" if contact is None else 'Solde dû (lecture seule)'
            form.addRow(label, self.debt)
            if contact is not None:
                self.debt.setReadOnly(True)
                self.debt.setEnabled(False)
            else:
                self.debt_due_enabled = QCheckBox('Définir une échéance')
                self.debt_due_date = QDateEdit(QDate.currentDate())
                self.debt_due_date.setCalendarPopup(True)
                self.debt_due_date.setEnabled(False)
                self.debt_due_enabled.toggled.connect(self.debt_due_date.setEnabled)
                due_row = QHBoxLayout()
                due_row.addWidget(self.debt_due_enabled)
                due_row.addWidget(self.debt_due_date)
                form.addRow(t('Échéance'), due_row)
        form.addRow(t('Notes'), self.notes)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        cancel = QPushButton(t('Annuler'))
        cancel.clicked.connect(self.reject)
        save = QPushButton(t('Enregistrer'))
        save.setObjectName('Primary')
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)
        if contact:
            self._fill(contact)

    def _fill(self, contact) -> None:
        self.name.setText(contact.name)
        self.phone.setText(contact.phone)
        self.phone2.setText(getattr(contact, 'phone2', '') or '')
        self.address.setText(contact.address)
        self.email.setText(contact.email)
        self.notes.setPlainText(contact.notes)
        if self.with_debt:
            self.debt.setValue(float(contact.debt))

    def _save(self) -> None:
        name = self.name.text().strip()
        phone = self.phone.text().strip()
        if not name and (not phone):
            warn(self, t('Le nom ou le téléphone est obligatoire.'))
            return
        if not name:
            name = f'Client {phone}'
        self.data = {'name': name, 'phone': phone, 'phone2': self.phone2.text().strip(), 'address': self.address.text().strip(), 'email': self.email.text().strip(), 'notes': self.notes.toPlainText().strip()}
        if self.with_debt and self.debt.isEnabled():
            self.data['debt'] = self.debt.value()
            if self.debt.value() > 0 and hasattr(self, 'debt_due_enabled') and self.debt_due_enabled.isChecked():
                qdate = self.debt_due_date.date()
                self.data['debt_due_date'] = qdate.toPython()
        self.accept()
