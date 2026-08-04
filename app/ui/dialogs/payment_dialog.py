"""Dialogue de paiement : modes multiples, monnaie, dette via téléphone client."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app import config
from app.controllers.client_controller import ClientController
from app.controllers.sale_controller import PaymentLine
from app.services import settings_service
from app.ui.widgets.client_search import ClientSearchField
from app.utils.helpers import format_money


class PaymentDialog(QDialog):
    """Recueille les paiements (éventuellement mixtes) pour une vente.

    L'option Dette est toujours proposée : elle s'active dès qu'un client
    est identifié (sélection préalable ou saisie du téléphone).
    """

    def __init__(
        self,
        total: float,
        client_id: Optional[int] = None,
        client_phone: str = "",
        allow_credit: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.total = float(total)
        self.currency = settings_service.get_currency()
        self.setWindowTitle("Paiement / Facture")
        self.setModal(True)
        self.setMinimumWidth(500)

        self.result_payments: List[PaymentLine] = []
        self.amount_received = 0.0
        self.change_due = 0.0
        self.use_credit = False
        self.credit_due_date = None
        self.result_client_id: Optional[int] = client_id
        self._resolved_client_name = ""
        self.allow_credit = allow_credit

        if client_id:
            client = ClientController.get(client_id)
            if client:
                self._resolved_client_name = client.name
                if not client_phone:
                    client_phone = client.phone or client.phone2 or ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header = QLabel(f"Total à payer : {format_money(self.total, self.currency)}")
        header.setObjectName("PageTitle")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        # --- Client (nom / téléphone) : suggestions progressives ----------------
        client_card = QFrame()
        client_card.setObjectName("Card")
        client_form = QFormLayout(client_card)
        client_form.setContentsMargins(16, 16, 16, 16)
        client_form.setSpacing(10)

        self.client_search = ClientSearchField(
            placeholder="Tapez un nom ou un téléphone…",
        )
        self.client_search.client_selected.connect(self._on_client_picked)
        client_form.addRow("Client", self.client_search)

        self.client_status = QLabel()
        self.client_status.setWordWrap(True)
        client_form.addRow("", self.client_status)
        layout.addWidget(client_card)

        if client_id:
            self.client_search.set_client(client_id)
        elif client_phone:
            self.client_search.input.setText(str(client_phone).strip())
            self.client_search._refresh_suggestions()

        hint = QLabel("Saisissez un ou plusieurs modes de paiement (paiement mixte).")
        hint.setStyleSheet("color: #64748b;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        methods_card = QFrame()
        methods_card.setObjectName("Card")
        form = QFormLayout(methods_card)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)

        self.credit_method = config.PAYMENT_METHOD_CREDIT
        self.method_inputs = {}
        for method in config.PAYMENT_METHODS:
            spin = self._make_spin()
            self.method_inputs[method] = spin
            form.addRow(method, spin)

        # Dette affichée à l'établissement du ticket, activée selon le rôle.
        self.credit_input = self._make_spin()
        self.method_inputs[self.credit_method] = self.credit_input
        self.credit_label = QLabel(self.credit_method)
        form.addRow(self.credit_label, self.credit_input)
        self.credit_hint = QLabel(
            "Pour porter le montant en dette, indiquez le téléphone du client ci-dessus."
        )
        self.credit_hint.setWordWrap(True)
        self.credit_hint.setStyleSheet("color: #b45309; font-size: 12px;")
        form.addRow("", self.credit_hint)
        self.credit_due_enabled = QCheckBox("Définir une échéance")
        self.credit_due_date_edit = QDateEdit(QDate.currentDate())
        self.credit_due_date_edit.setCalendarPopup(True)
        self.credit_due_date_edit.setEnabled(False)
        self.credit_due_enabled.toggled.connect(self.credit_due_date_edit.setEnabled)
        due_row = QHBoxLayout()
        due_row.addWidget(self.credit_due_enabled)
        due_row.addWidget(self.credit_due_date_edit)
        form.addRow("Échéance dette", due_row)
        layout.addWidget(methods_card)

        quick_row = QHBoxLayout()
        quick_cash = QPushButton("Payer le total en espèces")
        quick_cash.clicked.connect(self._pay_all_cash)
        quick_row.addWidget(quick_cash)
        self.quick_debt = QPushButton("Mettre tout en dette")
        self.quick_debt.setObjectName("Primary")
        self.quick_debt.clicked.connect(self._pay_all_credit)
        quick_row.addWidget(self.quick_debt)
        if not self.allow_credit:
            self.credit_label.setVisible(False)
            self.credit_input.setVisible(False)
            self.credit_hint.setVisible(False)
            self.credit_due_enabled.setVisible(False)
            self.credit_due_date_edit.setVisible(False)
            self.quick_debt.setVisible(False)
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

        self._refresh_client_status()
        self._recalculate()

    def _make_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 1_000_000_000)
        spin.setDecimals(0)
        spin.setSingleStep(500)
        spin.setSuffix(f" {self.currency}")
        spin.valueChanged.connect(self._recalculate)
        return spin

    # --- Client / téléphone ------------------------------------------------
    def _on_client_picked(self, client_id) -> None:
        if client_id:
            client = ClientController.get(int(client_id))
            self.result_client_id = int(client_id)
            self._resolved_client_name = client.name if client else ""
        else:
            self.result_client_id = None
            self._resolved_client_name = ""
        self._refresh_client_status()
        self._recalculate()

    def _typed_phone(self) -> str:
        text = self.client_search.text()
        return "".join(ch for ch in text if ch.isdigit() or ch == "+")

    def _resolve_client_from_typed(self) -> None:
        if self.client_search.client_id:
            self._on_client_picked(self.client_search.client_id)
            return
        phone = self._typed_phone()
        if not phone:
            self.result_client_id = None
            self._resolved_client_name = ""
            self._refresh_client_status()
            self._recalculate()
            return
        client = ClientController.find_by_phone(phone)
        if client:
            self.result_client_id = client.id
            self._resolved_client_name = client.name
            self.client_search.set_client(client.id)
        else:
            client = self._confirm_create_client(phone)
            if client:
                self.result_client_id = client.id
                self._resolved_client_name = client.name
        self._refresh_client_status()
        self._recalculate()

    def _confirm_create_client(self, phone: str):
        answer = QMessageBox.question(
            self,
            "Nouveau client",
            f"Aucun client trouvé pour « {phone} ».\n\nCréer une fiche client ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        default_name = f"Client {phone}"
        name, ok = QInputDialog.getText(
            self,
            "Nom du client",
            "Nom du client :",
            text=default_name,
        )
        if not ok:
            return None
        client = ClientController.find_or_create_by_phone(
            phone, name=(name or default_name).strip()
        )
        if client:
            self.client_search.set_client(client.id)
        return client

    def _ensure_client_for_credit(self) -> Optional[int]:
        """Garantit un client_id si Dette > 0 (sélection ou création via téléphone)."""
        if self.result_client_id:
            return self.result_client_id
        if self.client_search.client_id:
            self.result_client_id = self.client_search.client_id
            client = ClientController.get(self.result_client_id)
            self._resolved_client_name = client.name if client else ""
            self._refresh_client_status()
            return self.result_client_id
        phone = self._typed_phone()
        if not phone:
            return None
        client = ClientController.find_by_phone(phone)
        if not client:
            client = self._confirm_create_client(phone)
        if client:
            self.result_client_id = client.id
            self._resolved_client_name = client.name
            self.client_search.set_client(client.id)
            self._refresh_client_status()
        return self.result_client_id

    def _refresh_client_status(self) -> None:
        if not self.allow_credit:
            self.credit_hint.setText("Vous n'avez pas l'autorisation de vendre à crédit.")
            self.quick_debt.setEnabled(False)
            self.credit_input.setValue(0)
            self.credit_input.setEnabled(False)
            self.client_status.setText(
                "<span style='color:#64748b;'>Client facultatif pour la facture.</span>"
            )
            return
        if self.result_client_id and self._resolved_client_name:
            self.client_status.setText(
                f"<span style='color:#16a34a;'>Client sélectionné : "
                f"{self._resolved_client_name}</span>"
            )
            self.credit_hint.setText(
                "Choisissez « Dette » pour porter le montant sur le compte client."
            )
            self.quick_debt.setEnabled(True)
            self.credit_input.setEnabled(True)
        else:
            typed = self.client_search.text()
            if typed:
                self.client_status.setText(
                    "<span style='color:#b45309;'>Sélectionnez une suggestion "
                    "ou validez pour créer le client (téléphone).</span>"
                )
            else:
                self.client_status.setText(
                    "<span style='color:#64748b;'>Tapez un nom ou un téléphone — "
                    "les suggestions s'affichent au fur et à mesure.</span>"
                )
            self.credit_hint.setText(
                "Pour une dette, sélectionnez (ou créez) d'abord le client."
            )
            self.quick_debt.setEnabled(True)
            self.credit_input.setEnabled(True)

    # --- Calculs -----------------------------------------------------------
    def _credit_amount(self) -> float:
        return float(self.credit_input.value())

    def _cash_paid_total(self) -> float:
        total = 0.0
        for method, spin in self.method_inputs.items():
            if method == self.credit_method:
                continue
            total += float(spin.value())
        return total

    def _pay_all_cash(self) -> None:
        for method, spin in self.method_inputs.items():
            spin.blockSignals(True)
            spin.setValue(self.total if method == "Espèces" else 0)
            spin.blockSignals(False)
        self.received_input.setValue(self.total)
        self._recalculate()

    def _pay_all_credit(self) -> None:
        if not self.allow_credit:
            return
        if not self.result_client_id and self.client_search.text().strip():
            self._resolve_client_from_typed()
        for method, spin in self.method_inputs.items():
            spin.blockSignals(True)
            spin.setValue(self.total if method == self.credit_method else 0)
            spin.blockSignals(False)
        self.received_input.setValue(0)
        self._recalculate()

    def _cash_method_amount(self) -> float:
        """Montant réglé en espèces (base du calcul de la monnaie rendue)."""
        spin = self.method_inputs.get("Espèces")
        return float(spin.value()) if spin else 0.0

    def _recalculate(self) -> None:
        cash_paid = self._cash_paid_total()
        credit = self._credit_amount()
        covered = cash_paid + credit
        received = self.received_input.value()
        # La monnaie se calcule sur la part ESPÈCES (pas sur le total), afin de
        # rester correcte en cas de paiement mixte (Orange Money + espèces, ...).
        cash_due = self._cash_method_amount()
        change = max(0.0, received - cash_due) if received > 0 else 0.0
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
            if not self.result_client_id and not self.client_search.text().strip():
                parts.append(
                    "<span style='color:#dc2626;'>Sélectionnez un client "
                    "pour valider une dette.</span>"
                )
        if remaining > 0:
            parts.append(
                f"<span style='color:#dc2626;'>Montant insuffisant "
                f"({format_money(remaining, self.currency)} manquant)</span>"
            )
        elif credit > 0 and cash_paid <= 0 and (
            self.result_client_id or self.client_search.text().strip()
        ):
            parts.append(
                "<span style='color:#f59e0b;'>Vente entièrement portée en dette</span>"
            )
        elif remaining <= 0 and credit <= 0:
            parts.append("<span style='color:#16a34a;'>Paiement suffisant</span>")
        elif remaining <= 0:
            parts.append("<span style='color:#16a34a;'>Paiement suffisant</span>")

        self.summary.setText("<br>".join(parts))

        credit_ok = credit <= 0 or bool(
            self.result_client_id or self.client_search.text().strip()
        )
        self.validate.setEnabled(covered >= self.total and credit_ok)

    def _confirm(self) -> None:
        cash_paid = self._cash_paid_total()
        credit = self._credit_amount()
        if credit > 0 and not self.allow_credit:
            return
        if cash_paid + credit < self.total:
            return
        if credit > 0:
            client_id = self._ensure_client_for_credit()
            if not client_id:
                self.summary.setText(
                    "<span style='color:#dc2626;'>Sélectionnez un client "
                    "pour valider une dette.</span>"
                )
                return
        elif self.client_search.text().strip() and not self.result_client_id:
            # Facture nominative même sans dette.
            self._resolve_client_from_typed()

        self.result_payments = [
            PaymentLine(method=method, amount=spin.value())
            for method, spin in self.method_inputs.items()
            if spin.value() > 0
        ]
        cash_due = self._cash_method_amount()
        self.amount_received = self.received_input.value() or cash_due
        self.change_due = max(0.0, self.amount_received - cash_due)
        self.use_credit = credit > 0
        if credit > 0 and self.credit_due_enabled.isChecked():
            self.credit_due_date = self.credit_due_date_edit.date().toPython()
        else:
            self.credit_due_date = None
        self.accept()
