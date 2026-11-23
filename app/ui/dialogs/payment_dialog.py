"""Dialogue de paiement : modes multiples, monnaie, dette via téléphone client."""
from __future__ import annotations
from app.i18n import t
from typing import List, Optional
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QCheckBox, QDateEdit, QDialog, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget
from app import config
from app.controllers.client_controller import ClientController
from app.controllers.sale_controller import PaymentLine
from app.services import settings_service
from app.ui.widgets.client_search import ClientSearchField
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.utils.helpers import format_money
from app.ui.widgets.money_spin import MoneySpinBox

class PaymentDialog(QDialog):
    """Recueille les paiements (éventuellement mixtes) pour une vente.

    L'option Dette est toujours proposée : elle s'active dès qu'un client
    est identifié (sélection préalable ou saisie du téléphone).
    """

    def __init__(self, total: float, client_id: Optional[int]=None, client_phone: str='', allow_credit: bool=True, max_credit: Optional[float]=None, parent=None):
        super().__init__(parent)
        self.total = float(total)
        self.currency = settings_service.get_currency()
        self.setWindowTitle(t('Paiement / Facture'))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=400, min_height=320, preferred_width=700, preferred_height=620)
        self.result_payments: List[PaymentLine] = []
        self.amount_received = 0.0
        self.change_due = 0.0
        self.use_credit = False
        self.credit_due_date = None
        self.result_client_id: Optional[int] = client_id
        self._resolved_client_name = ''
        self.allow_credit = allow_credit
        self.max_credit = max_credit
        if client_id:
            client = ClientController.get(client_id)
            if client:
                self._resolved_client_name = client.name
                if not client_phone:
                    client_phone = client.phone or client.phone2 or ''
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header_banner = QFrame()
        header_banner.setObjectName('DialogHeaderBanner')
        header_layout = QVBoxLayout(header_banner)
        header_layout.setContentsMargins(20, 14, 20, 16)
        header_layout.setSpacing(2)
        header_caption = QLabel(t('TOTAL À PAYER').upper())
        header_caption.setStyleSheet('font-size: 11px; font-weight: 700; letter-spacing: 1px;')
        header_layout.addWidget(header_caption)
        header = QLabel(format_money(self.total, self.currency))
        header.setStyleSheet('font-size: 26px; font-weight: 800;')
        header_layout.addWidget(header)
        outer.addWidget(header_banner)
        content = QVBoxLayout()
        content.setContentsMargins(12, 12, 12, 12)
        content.setSpacing(8)
        outer.addLayout(content, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 8, 4)
        layout.setSpacing(10)
        client_card = QFrame()
        client_card.setObjectName('Card')
        client_form = QFormLayout(client_card)
        client_form.setContentsMargins(12, 12, 12, 12)
        client_form.setSpacing(8)
        self.client_search = ClientSearchField(placeholder='Tapez un nom ou un téléphone…')
        self.client_search.client_selected.connect(self._on_client_picked)
        client_form.addRow(t('Client'), self.client_search)
        self.client_status = QLabel()
        self.client_status.setWordWrap(True)
        client_form.addRow('', self.client_status)
        layout.addWidget(client_card)
        if client_id:
            self.client_search.set_client(client_id)
        elif client_phone:
            self.client_search.input.setText(str(client_phone).strip())
            self.client_search._refresh_suggestions()
        hint = QLabel(t('Saisissez un ou plusieurs modes de paiement (paiement mixte).'))
        hint.setStyleSheet('color: #64748b;')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        methods_card = QFrame()
        methods_card.setObjectName('Card')
        methods_outer = QVBoxLayout(methods_card)
        methods_outer.setContentsMargins(12, 12, 12, 12)
        methods_outer.setSpacing(10)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        def _method_card(label_text: str):
            card = QFrame()
            card.setObjectName('SmallCard')
            inner = QVBoxLayout(card)
            inner.setContentsMargins(10, 8, 10, 8)
            inner.setSpacing(2)
            lbl = QLabel(label_text)
            lbl.setStyleSheet('font-size: 11.5px; font-weight: 700; color: #64748b; border: none; background: transparent;')
            spin = self._make_spin()
            spin.setStyleSheet('font-size: 15px; font-weight: 700; border: none; background: transparent; padding: 0;')
            inner.addWidget(lbl)
            inner.addWidget(spin)
            return card, spin

        self.credit_method = config.PAYMENT_METHOD_CREDIT
        self.method_inputs = {}
        self.method_cards = {}
        for index, method in enumerate(config.PAYMENT_METHODS):
            card, spin = _method_card(method)
            self.method_inputs[method] = spin
            self.method_cards[method] = card
            row, col = divmod(index, 2)
            grid.addWidget(card, row, col)
        methods_outer.addLayout(grid)
        self.credit_card = QFrame()
        self.credit_card.setObjectName('AmberCard')
        credit_inner = QVBoxLayout(self.credit_card)
        credit_inner.setContentsMargins(10, 8, 10, 8)
        credit_inner.setSpacing(2)
        self.credit_label = QLabel(self.credit_method)
        self.credit_label.setStyleSheet('font-size: 11.5px; font-weight: 700; color: #b45309; border: none; background: transparent;')
        self.credit_input = self._make_spin()
        self.credit_input.setStyleSheet('font-size: 15px; font-weight: 700; border: none; background: transparent; padding: 0;')
        if self.max_credit is not None:
            self.credit_input.setMaximum(min(self.total, float(self.max_credit)))
            self.credit_input.setToolTip(f'Plafond caissier : {format_money(self.max_credit, self.currency)}')
        self.method_inputs[self.credit_method] = self.credit_input
        credit_inner.addWidget(self.credit_label)
        credit_inner.addWidget(self.credit_input)
        methods_outer.addWidget(self.credit_card)
        hint = 'Pour porter le montant en dette, indiquez le téléphone du client ci-dessus.'
        if self.max_credit is not None:
            hint += f' Plafond caissier : {format_money(self.max_credit, self.currency)}.'
        self.credit_hint = QLabel(hint)
        self.credit_hint.setWordWrap(True)
        self.credit_hint.setStyleSheet('color: #b45309; font-size: 12px;')
        methods_outer.addWidget(self.credit_hint)
        self.credit_due_enabled = QCheckBox('Définir une échéance')
        self.credit_due_date_edit = QDateEdit(QDate.currentDate())
        self.credit_due_date_edit.setCalendarPopup(True)
        self.credit_due_date_edit.setEnabled(False)
        self.credit_due_enabled.toggled.connect(self.credit_due_date_edit.setEnabled)
        due_row = QHBoxLayout()
        self.credit_due_label = QLabel(t('Échéance dette'))
        due_row.addWidget(self.credit_due_label)
        due_row.addWidget(self.credit_due_enabled)
        due_row.addWidget(self.credit_due_date_edit)
        due_row.addStretch()
        methods_outer.addLayout(due_row)
        layout.addWidget(methods_card)
        quick_row = QHBoxLayout()
        quick_cash = QPushButton(t('Payer le total en espèces'))
        quick_cash.clicked.connect(self._pay_all_cash)
        quick_row.addWidget(quick_cash)
        self.quick_debt = QPushButton(t('Mettre tout en dette'))
        self.quick_debt.setObjectName('Primary')
        self.quick_debt.clicked.connect(self._pay_all_credit)
        quick_row.addWidget(self.quick_debt)
        if not self.allow_credit:
            self.credit_card.setVisible(False)
            self.credit_hint.setVisible(False)
            self.credit_due_label.setVisible(False)
            self.credit_due_enabled.setVisible(False)
            self.credit_due_date_edit.setVisible(False)
            self.quick_debt.setVisible(False)
        layout.addLayout(quick_row)
        received_row = QFormLayout()
        self.received_input = MoneySpinBox()
        self.received_input.setRange(0, 1000000000)
        self.received_input.setDecimals(3)
        self.received_input.setSingleStep(500)
        self.received_input.setSuffix(f' {self.currency}')
        self.received_input.valueChanged.connect(self._recalculate)
        received_row.addRow(t('Argent reçu (espèces)'), self.received_input)
        layout.addLayout(received_row)
        summary_banner = QFrame()
        summary_banner.setObjectName('DialogSummaryBanner')
        summary_layout = QVBoxLayout(summary_banner)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        self.summary = QLabel()
        self.summary.setStyleSheet('font-size: 13.5px;')
        self.summary.setWordWrap(True)
        summary_layout.addWidget(self.summary)
        layout.addWidget(summary_banner)
        layout.addStretch(1)
        scroll.setWidget(body)
        content.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        cancel = QPushButton(t('Annuler'))
        cancel.clicked.connect(self.reject)
        self.validate = QPushButton(t('Valider le paiement'))
        self.validate.setObjectName('Success')
        self.validate.clicked.connect(self._confirm)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(self.validate)
        content.addLayout(buttons)
        self._refresh_client_status()
        self._recalculate()

    def _make_spin(self) -> QDoubleSpinBox:
        spin = MoneySpinBox()
        spin.setRange(0, 1000000000)
        spin.setDecimals(3)
        spin.setSingleStep(500)
        spin.setSuffix(f' {self.currency}')
        spin.valueChanged.connect(self._recalculate)
        return spin

    def _on_client_picked(self, client_id) -> None:
        if client_id:
            client = ClientController.get(int(client_id))
            self.result_client_id = int(client_id)
            self._resolved_client_name = client.name if client else ''
        else:
            self.result_client_id = None
            self._resolved_client_name = ''
        self._refresh_client_status()
        self._recalculate()

    def _typed_phone(self) -> str:
        text = self.client_search.text()
        return ''.join((ch for ch in text if ch.isdigit() or ch == '+'))

    def _resolve_client_from_typed(self) -> None:
        if self.client_search.client_id:
            self._on_client_picked(self.client_search.client_id)
            return
        typed = self.client_search.text()
        if not typed:
            self.result_client_id = None
            self._resolved_client_name = ''
            self._refresh_client_status()
            self._recalculate()
            return
        phone = self._typed_phone()
        if phone:
            client = ClientController.find_by_phone(phone)
            if client:
                self.result_client_id = client.id
                self._resolved_client_name = client.name
                self.client_search.set_client(client.id)
            else:
                client = self._confirm_create_client(phone=phone)
                if client:
                    self.result_client_id = client.id
                    self._resolved_client_name = client.name
        else:
            client = self._confirm_create_client(name_hint=typed)
            if client:
                self.result_client_id = client.id
                self._resolved_client_name = client.name
        self._refresh_client_status()
        self._recalculate()

    def _confirm_create_client(self, phone: str='', name_hint: str=''):
        """Ouvre un formulaire complet (nom + téléphone) pour créer un nouveau client.

        Pré-remplit les champs avec ce qui a déjà été saisi dans le champ client,
        afin que le premier enregistrement capture toujours les deux informations.
        """
        from app.ui.dialogs.contact_dialog import ContactDialog
        display = phone or name_hint
        answer = QMessageBox.question(self, 'Nouveau client', f'Aucun client trouvé pour « {display} ».\n\nCréer une fiche client ? (nom et téléphone recommandés)', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return None
        dialog = ContactDialog('Nouveau client', with_debt=False, parent=self)
        if name_hint:
            dialog.name.setText(name_hint)
        if phone:
            dialog.phone.setText(phone)
        if not dialog.exec() or not dialog.data:
            return None
        final_phone = dialog.data.get('phone', '').strip()
        if final_phone:
            existing = ClientController.find_by_phone(final_phone)
            if existing:
                self.client_search.set_client(existing.id)
                return existing
        client = ClientController.create(dialog.data)
        if client:
            self.client_search.set_client(client.id)
        return client

    def _ensure_client_for_credit(self) -> Optional[int]:
        """Garantit un client_id si Dette > 0 (sélection, téléphone ou nom)."""
        if self.result_client_id:
            return self.result_client_id
        if self.client_search.client_id:
            self.result_client_id = self.client_search.client_id
            client = ClientController.get(self.result_client_id)
            self._resolved_client_name = client.name if client else ''
            self._refresh_client_status()
            return self.result_client_id
        typed = self.client_search.text()
        if not typed:
            return None
        phone = self._typed_phone()
        if phone:
            client = ClientController.find_by_phone(phone)
            if not client:
                client = self._confirm_create_client(phone=phone)
        else:
            client = self._confirm_create_client(name_hint=typed)
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
            self.client_status.setText("<span style='color:#64748b;'>Client facultatif pour la facture.</span>")
            return
        if self.result_client_id and self._resolved_client_name:
            self.client_status.setText(f"<span style='color:#16a34a;'>Client sélectionné : {self._resolved_client_name}</span>")
            self.credit_hint.setText('Choisissez « Dette » pour porter le montant sur le compte client.')
            self.quick_debt.setEnabled(True)
            self.credit_input.setEnabled(True)
        else:
            typed = self.client_search.text()
            if typed:
                self.client_status.setText("<span style='color:#b45309;'>Sélectionnez une suggestion ou validez pour créer le client (téléphone).</span>")
            else:
                self.client_status.setText("<span style='color:#64748b;'>Tapez un nom ou un téléphone — les suggestions s'affichent au fur et à mesure.</span>")
            self.credit_hint.setText("Pour une dette, sélectionnez (ou créez) d'abord le client.")
            self.quick_debt.setEnabled(True)
            self.credit_input.setEnabled(True)

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
            spin.setValue(self.total if method == 'Espèces' else 0)
            spin.blockSignals(False)
        self.received_input.setValue(self.total)
        self._recalculate()

    def _pay_all_credit(self) -> None:
        if not self.allow_credit:
            return
        if not self.result_client_id and self.client_search.text().strip():
            self._resolve_client_from_typed()
        credit_value = self.total
        if self.max_credit is not None:
            credit_value = min(credit_value, float(self.max_credit))
        for method, spin in self.method_inputs.items():
            spin.blockSignals(True)
            spin.setValue(credit_value if method == self.credit_method else 0)
            spin.blockSignals(False)
        self.received_input.setValue(0)
        self._recalculate()
        if self.max_credit is not None and self.total > float(self.max_credit):
            self.summary.setText(f"<span style='color:#fbbf24;'>Plafond dette caissier : {format_money(self.max_credit, self.currency)} (reste à encaisser autrement).</span>")

    def _cash_method_amount(self) -> float:
        """Montant réglé en espèces (base du calcul de la monnaie rendue)."""
        spin = self.method_inputs.get('Espèces')
        return float(spin.value()) if spin else 0.0

    def _recalculate(self) -> None:
        cash_paid = self._cash_paid_total()
        credit = self._credit_amount()
        covered = cash_paid + credit
        received = self.received_input.value()
        cash_due = self._cash_method_amount()
        change = max(0.0, received - cash_due) if received > 0 else 0.0
        remaining = max(0.0, self.total - covered)
        for method, card in self.method_cards.items():
            spin = self.method_inputs.get(method)
            self._set_card_active(card, bool(spin and spin.value() > 0))
        parts = [
            f"<span style='color:#e2e8f0;'>Encaissé : {format_money(cash_paid, self.currency)}</span>",
            f"<span style='color:#93c5fd; font-weight:700;'>Monnaie à rendre : {format_money(change, self.currency)}</span>",
        ]
        if credit > 0:
            parts.append(f"<span style='color:#fbbf24;'>Dette client : {format_money(credit, self.currency)}</span>")
            if not self.result_client_id and (not self.client_search.text().strip()):
                parts.append("<span style='color:#f87171;'>Sélectionnez un client pour valider une dette.</span>")
        if remaining > 0:
            parts.append(f"<span style='color:#f87171;'>Montant insuffisant ({format_money(remaining, self.currency)} manquant)</span>")
        elif credit > 0 and cash_paid <= 0 and (self.result_client_id or self.client_search.text().strip()):
            parts.append("<span style='color:#fbbf24;'>Vente entièrement portée en dette</span>")
        elif remaining <= 0 and credit <= 0:
            parts.append("<span style='color:#4ade80;'>✓ Paiement suffisant</span>")
        elif remaining <= 0:
            parts.append("<span style='color:#4ade80;'>✓ Paiement suffisant</span>")
        self.summary.setText('<br>'.join(parts))
        credit_ok = credit <= 0 or bool(self.result_client_id or self.client_search.text().strip())
        self.validate.setEnabled(covered >= self.total and credit_ok)

    def _set_card_active(self, card: QFrame, active: bool) -> None:
        card.setObjectName('SmallCardActive' if active else 'SmallCard')
        card.style().unpolish(card)
        card.style().polish(card)

    def _confirm(self) -> None:
        cash_paid = self._cash_paid_total()
        credit = self._credit_amount()
        if credit > 0 and (not self.allow_credit):
            return
        if self.max_credit is not None and credit > float(self.max_credit) + 0.009:
            self.summary.setText(f"<span style='color:#f87171;'>Dette plafonnée à {format_money(self.max_credit, self.currency)} pour un caissier.</span>")
            return
        if cash_paid + credit < self.total:
            return
        if credit > 0:
            client_id = self._ensure_client_for_credit()
            if not client_id:
                self.summary.setText("<span style='color:#f87171;'>Sélectionnez un client pour valider une dette.</span>")
                return
        elif self.client_search.text().strip() and (not self.result_client_id):
            self._resolve_client_from_typed()
        self.result_payments = [PaymentLine(method=method, amount=spin.value()) for method, spin in self.method_inputs.items() if spin.value() > 0]
        cash_due = self._cash_method_amount()
        self.amount_received = self.received_input.value() or cash_due
        self.change_due = max(0.0, self.amount_received - cash_due)
        self.use_credit = credit > 0
        if credit > 0 and self.credit_due_enabled.isChecked():
            self.credit_due_date = self.credit_due_date_edit.date().toPython()
        else:
            self.credit_due_date = None
        self.accept()
