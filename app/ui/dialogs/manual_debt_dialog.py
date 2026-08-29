"""Dialogue admin : saisie libre d'une dette client (hors caisse)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.controllers.client_controller import ClientController
from app.ui.dialogs.contact_dialog import ContactDialog
from app.ui.widgets.client_search import ClientSearchField
from app.ui.widgets.helpers import warn


class ManualDebtDialog(QDialog):
    """Enregistre une dette manuelle pour un client existant (ou à créer)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouvelle dette (hors caisse)")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.result_data: Optional[dict] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        hint = QLabel(
            "Saisie libre réservée à l'administrateur — "
            "sans passer par la caisse."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b;")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)

        self.client_search = ClientSearchField(self)
        form.addRow("Client", self.client_search)

        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000_000)
        self.amount.setDecimals(0)
        self.amount.setValue(0)
        form.addRow("Montant", self.amount)

        self.due_enabled = QCheckBox("Définir une échéance")
        self.due_date = QDateEdit(QDate.currentDate().addDays(7))
        self.due_date.setCalendarPopup(True)
        self.due_date.setEnabled(False)
        self.due_enabled.toggled.connect(self.due_date.setEnabled)
        due_row = QHBoxLayout()
        due_row.addWidget(self.due_enabled)
        due_row.addWidget(self.due_date)
        form.addRow("Échéance", due_row)

        self.note = QLineEdit()
        self.note.setPlaceholderText("Motif / commentaire (facultatif)")
        form.addRow("Note", self.note)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Enregistrer la dette")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _resolve_client_id(self) -> Optional[int]:
        if self.client_search.client_id:
            return self.client_search.client_id

        typed = self.client_search.text()
        if not typed:
            return None

        phone = "".join(ch for ch in typed if ch.isdigit() or ch == "+")
        if phone:
            existing = ClientController.find_by_phone(phone)
            if existing:
                self.client_search.set_client(existing.id)
                return existing.id

        answer = QMessageBox.question(
            self,
            "Nouveau client",
            f"Aucun client trouvé pour « {typed} ».\n\n"
            "Créer une fiche client pour cette dette ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None

        dialog = ContactDialog("Nouveau client", with_debt=False, parent=self)
        if phone:
            dialog.phone.setText(phone)
        else:
            dialog.name.setText(typed)
        if not dialog.exec() or not dialog.data:
            return None

        final_phone = (dialog.data.get("phone") or "").strip()
        if final_phone:
            existing = ClientController.find_by_phone(final_phone)
            if existing:
                self.client_search.set_client(existing.id)
                return existing.id

        client = ClientController.create(dialog.data)
        if not client:
            return None
        self.client_search.set_client(client.id)
        return client.id

    def _save(self) -> None:
        amount = float(self.amount.value())
        if amount <= 0:
            warn(self, "Indiquez un montant supérieur à zéro.")
            return
        client_id = self._resolve_client_id()
        if not client_id:
            warn(self, "Sélectionnez ou créez un client.")
            return
        due = None
        if self.due_enabled.isChecked():
            due = self.due_date.date().toPython()
        note = self.note.text().strip() or "Dette manuelle (hors caisse)"
        self.result_data = {
            "client_id": client_id,
            "amount": amount,
            "due_date": due,
            "note": note,
        }
        self.accept()
