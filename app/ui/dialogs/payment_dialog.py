"""Dialogue de paiement : modes multiples, monnaie, dette via téléphone client."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app import config
from app.controllers.client_controller import ClientController
from app.controllers.sale_controller import PaymentLine
from app.services import settings_service
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

        # --- Client / téléphone (requis pour Dette et facture nominative) ---
        client_card = QFrame()
        client_card.setObjectName("Card")
        client_form = QFormLayout(client_card)
        client_form.setContentsMargins(16, 16, 16, 16)
        client_form.setSpacing(10)

        phone_row = QHBoxLayout()
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Numéro de téléphone du client")
        self.phone_input.setText(str(client_phone or "").strip())
        self.phone_input.returnPressed.connect(self._resolve_client_from_phone)
        self.phone_input.textChanged.connect(self._on_phone_edited)
        phone_row.addWidget(self.phone_input, 1)
        find_btn = QPushButton("Rechercher")
        find_btn.clicked.connect(self._resolve_client_from_phone)
        phone_row.addWidget(find_btn)
        client_form.addRow("Téléphone", phone_row)

        self.client_status = QLabel()
        self.client_status.setWordWrap(True)
        client_form.addRow("Client", self.client_status)
        layout.addWidget(client_card)

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
    def _on_phone_edited(self, _text: str = "") -> None:
        # Si l'utilisateur modifie le téléphone, on invalide la résolution
        # sauf si elle correspond encore.
        phone = self.phone_input.text().strip()
        if self.result_client_id:
            client = ClientController.get(self.result_client_id)
            phones = {
                (client.phone or "").strip(),
                (client.phone2 or "").strip(),
            } if client else set()
            if phone and phone not in phones and not any(
                phone in p for p in phones if p
            ):
                # Conservé tant qu'on n'a pas re-recherché ; le statut reste.
                pass
        self._refresh_client_status()
        self._recalculate()

    def _resolve_client_from_phone(self) -> None:
        phone = self.phone_input.text().strip()
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
        else:
            # Création automatique pour pouvoir facturer / mettre en dette.
            client = ClientController.find_or_create_by_phone(phone)
            if client:
                self.result_client_id = client.id
                self._resolved_client_name = client.name
        self._refresh_client_status()
        self._recalculate()

    def _ensure_client_for_credit(self) -> Optional[int]:
        """Garantit un client_id si Dette > 0 (recherche / création via téléphone)."""
        if self.result_client_id:
            return self.result_client_id
        phone = self.phone_input.text().strip()
        if not phone:
            return None
        client = ClientController.find_or_create_by_phone(phone)
        if client:
            self.result_client_id = client.id
            self._resolved_client_name = client.name
            self._refresh_client_status()
        return self.result_client_id

    def _refresh_client_status(self) -> None:
        if not self.allow_credit:
            self.credit_hint.setText("La vente à crédit est réservée au gestionnaire.")
            self.quick_debt.setEnabled(False)
            self.credit_input.setValue(0)
            self.credit_input.setEnabled(False)
            self.client_status.setText(
                "<span style='color:#64748b;'>Client facultatif pour la facture.</span>"
            )
            return
        if self.result_client_id and self._resolved_client_name:
            phone = self.phone_input.text().strip()
            suffix = f" — {phone}" if phone else ""
            self.client_status.setText(
                f"<span style='color:#16a34a;'>{self._resolved_client_name}{suffix}</span>"
            )
            self.credit_hint.setText(
                "Choisissez « Dette » pour porter le montant sur le compte client."
            )
            self.quick_debt.setEnabled(True)
            self.credit_input.setEnabled(True)
        else:
            phone = self.phone_input.text().strip()
            if phone:
                self.client_status.setText(
                    "<span style='color:#b45309;'>Appuyez sur Rechercher "
                    "(le client sera créé s'il n'existe pas).</span>"
                )
            else:
                self.client_status.setText(
                    "<span style='color:#64748b;'>Client de passage — "
                    "saisissez un téléphone pour facturer ou mettre en dette.</span>"
                )
            self.credit_hint.setText(
                "Pour porter le montant en dette, indiquez le téléphone du client."
            )
            # Dette saisissable même sans client : la validation créera / liera le client.
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
        phone = self.phone_input.text().strip()
        if not self.result_client_id and phone:
            self._resolve_client_from_phone()
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
            if not self.result_client_id and not self.phone_input.text().strip():
                parts.append(
                    "<span style='color:#dc2626;'>Indiquez le téléphone du client "
                    "pour valider une dette.</span>"
                )
        if remaining > 0:
            parts.append(
                f"<span style='color:#dc2626;'>Montant insuffisant "
                f"({format_money(remaining, self.currency)} manquant)</span>"
            )
        elif credit > 0 and cash_paid <= 0 and (
            self.result_client_id or self.phone_input.text().strip()
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
            self.result_client_id or self.phone_input.text().strip()
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
                    "<span style='color:#dc2626;'>Indiquez le téléphone du client "
                    "pour valider une dette.</span>"
                )
                return
        elif self.phone_input.text().strip() and not self.result_client_id:
            # Facture nominative même sans dette.
            self._resolve_client_from_phone()

        self.result_payments = [
            PaymentLine(method=method, amount=spin.value())
            for method, spin in self.method_inputs.items()
            if spin.value() > 0
        ]
        self.amount_received = self.received_input.value() or cash_paid
        self.change_due = max(0.0, self.amount_received - self._cash_method_amount())
        self.use_credit = credit > 0
        self.accept()
