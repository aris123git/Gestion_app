"""Dialogue générique pour un contact (client ou fournisseur)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.ui.widgets.helpers import warn


class ContactDialog(QDialog):
    """Formulaire nom/téléphone/adresse/email (+ dette pour les clients)."""

    def __init__(self, title: str, contact=None, with_debt: bool = False, parent=None):
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
        self.address = QLineEdit()
        self.email = QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(70)

        form.addRow("Nom *", self.name)
        form.addRow("Téléphone", self.phone)
        form.addRow("Adresse", self.address)
        form.addRow("Email", self.email)

        if with_debt:
            self.debt = QDoubleSpinBox()
            self.debt.setRange(0, 1_000_000_000)
            self.debt.setDecimals(0)
            form.addRow("Dette actuelle", self.debt)

        form.addRow("Notes", self.notes)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Enregistrer")
        save.setObjectName("Primary")
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
        self.address.setText(contact.address)
        self.email.setText(contact.email)
        self.notes.setPlainText(contact.notes)
        if self.with_debt:
            self.debt.setValue(float(contact.debt))

    def _save(self) -> None:
        if not self.name.text().strip():
            warn(self, "Le nom est obligatoire.")
            return
        self.data = {
            "name": self.name.text().strip(),
            "phone": self.phone.text().strip(),
            "address": self.address.text().strip(),
            "email": self.email.text().strip(),
            "notes": self.notes.toPlainText().strip(),
        }
        if self.with_debt:
            self.data["debt"] = self.debt.value()
        self.accept()
