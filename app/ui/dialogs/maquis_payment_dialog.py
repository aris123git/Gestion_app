"""Paiement Maquis — pavé numérique et modes (parité PaymentDialog.kt)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.i18n import t
from app.services import settings_service
from app.services.maquis_payment import (
    FIELD_CASH,
    FIELD_DEBT,
    FIELD_MOBILE,
    FIELD_TENDERED,
    FIELD_VOUCHER,
    MODE_CARD,
    MODE_CASH,
    MODE_DEBT,
    MODE_MIXED,
    MODE_MOOV,
    MODE_ORANGE,
    MODE_OTHER,
    MODE_WAVE,
    PAYMENT_CHOICES,
    PaymentBreakdown,
    PaymentInput,
    preview_change,
    simple_pay,
    validate,
)
from app.ui.widgets.client_search import ClientSearchField
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.numeric_keypad import NumericKeypad
from app.utils.helpers import format_money


@dataclass
class MaquisPaymentResult:
    breakdown: PaymentBreakdown
    change_amount: float
    debt_client_id: Optional[int] = None
    partial_with_debt_remainder: bool = False


class MaquisPaymentDialog(QDialog):
    """Encaissement commande / caisse Maquis."""

    def __init__(
        self,
        total: float,
        parent=None,
        *,
        allow_partial: bool = False,
        allow_credit: bool = True,
    ):
        super().__init__(parent)
        self.total = _round(total)
        self.allow_partial = allow_partial
        self.allow_credit = allow_credit
        self.result_data: Optional[MaquisPaymentResult] = None
        self._mode = MODE_CASH
        self._active_field = FIELD_TENDERED
        self._amount_tendered = str(int(self.total)) if self.total == int(self.total) else str(self.total)
        self._tendered_explicit = True
        self._cash = ""
        self._mobile = ""
        self._voucher = ""
        self._debt = ""
        self._partial = False
        self._debt_remainder = False
        self.setWindowTitle(t("Paiement"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=420, min_height=520, preferred_width=520, preferred_height=720)
        self.currency = settings_service.get_currency()
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        self._total_label = QLabel(
            f"{t('Total')} : {format_money(self.total, self.currency)}"
        )
        self._total_label.setObjectName("PageTitle")
        self._total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._total_label)
        self._change_label = QLabel("")
        self._change_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._change_label)
        self._error = QLabel("")
        self._error.setStyleSheet("color: #dc2626;")
        self._error.setWordWrap(True)
        layout.addWidget(self._error)
        modes = QGridLayout()
        self._mode_buttons: dict[str, QPushButton] = {}
        all_modes = list(PAYMENT_CHOICES)
        if allow_credit:
            all_modes.append(MODE_DEBT)
        for i, mode in enumerate(all_modes):
            b = QPushButton(mode)
            b.clicked.connect(lambda _=False, m=mode: self._select_mode(m))
            self._mode_buttons[mode] = b
            modes.addWidget(b, i // 3, i % 3)
        layout.addLayout(modes)
        self._mixed_panel = QWidget()
        mp = QVBoxLayout(self._mixed_panel)
        self._mixed_labels = {
            FIELD_CASH: t("Espèces"),
            FIELD_MOBILE: MODE_ORANGE,
            FIELD_VOUCHER: MODE_MOOV,
            FIELD_DEBT: t("Dette"),
            FIELD_TENDERED: t("Espèces tendues (opt.)"),
        }
        self._mixed_chips: dict[str, QPushButton] = {}
        for field, label in self._mixed_labels.items():
            chip = QPushButton(label)
            chip.clicked.connect(lambda _=False, f=field: self._select_field(f))
            self._mixed_chips[field] = chip
            mp.addWidget(chip)
        layout.addWidget(self._mixed_panel)
        if allow_partial:
            self._partial_cb = QCheckBox(t("Paiement partiel (montant libre)"))
            self._partial_cb.toggled.connect(self._on_partial_toggled)
            layout.addWidget(self._partial_cb)
            self._debt_rest_cb = QCheckBox(t("Mettre le reste en dette"))
            self._debt_rest_cb.setVisible(False)
            layout.addWidget(self._debt_rest_cb)
        else:
            self._partial_cb = None
            self._debt_rest_cb = None
        self._client_row = QWidget()
        cr = QVBoxLayout(self._client_row)
        cr.addWidget(QLabel(t("Client (dette)")))
        self.client_search = ClientSearchField()
        cr.addWidget(self.client_search)
        layout.addWidget(self._client_row)
        self._keypad = NumericKeypad(confirm_label=t("Encaisser"))
        self._keypad.value_changed.connect(self._on_keypad)
        self._keypad.confirm_pressed.connect(self._confirm)
        layout.addWidget(self._keypad)
        self._confirm_simple = QPushButton(t("Encaisser"))
        self._confirm_simple.setObjectName("Primary")
        self._confirm_simple.setMinimumHeight(52)
        self._confirm_simple.clicked.connect(self._confirm)
        layout.addWidget(self._confirm_simple)
        cancel = QPushButton(t("Annuler"))
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)
        scroll.setWidget(body)
        root.addWidget(scroll)
        self._select_mode(MODE_CASH)
        self._refresh_ui()

    @staticmethod
    def _round(v: float) -> float:
        return round(float(v), 2)

    def _parse(self, s: str) -> float:
        s = (s or "").strip().replace(",", ".")
        if not s or s == "—":
            return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0

    def _select_mode(self, mode: str) -> None:
        self._mode = mode
        self._error.setText("")
        if mode == MODE_CASH:
            self._active_field = FIELD_TENDERED
            if not self._amount_tendered:
                self._amount_tendered = str(int(self.total) if self.total == int(self.total) else self.total)
            self._tendered_explicit = True
        elif mode == MODE_MIXED:
            self._active_field = FIELD_CASH
            if not self._cash:
                self._cash = str(int(self.total) if self.total == int(self.total) else self.total)
            self._tendered_explicit = False
        else:
            self._active_field = FIELD_TENDERED
        for m, btn in self._mode_buttons.items():
            btn.setStyleSheet(
                "font-weight: 700;" if m == mode else ""
            )
        self._mixed_panel.setVisible(mode == MODE_MIXED)
        self._client_row.setVisible(mode in (MODE_DEBT, MODE_MIXED) or (self._debt_rest_cb and self._debt_rest_cb.isChecked()))
        partial = self._partial_cb and self._partial_cb.isChecked()
        needs_keypad = mode in (MODE_CASH, MODE_MIXED) or partial
        self._keypad.setVisible(needs_keypad)
        self._confirm_simple.setVisible(not needs_keypad)
        self._refresh_ui()

    def _select_field(self, field: str) -> None:
        self._active_field = field
        if field == FIELD_TENDERED:
            self._tendered_explicit = True
        self._refresh_ui()

    def _on_partial_toggled(self, checked: bool) -> None:
        if self._debt_rest_cb:
            self._debt_rest_cb.setVisible(checked)
        self._select_mode(self._mode)

    def _active_value(self) -> str:
        if self._mode == MODE_MIXED:
            return {
                FIELD_TENDERED: self._amount_tendered if self._tendered_explicit else "—",
                FIELD_CASH: self._cash,
                FIELD_MOBILE: self._mobile,
                FIELD_VOUCHER: self._voucher,
                FIELD_DEBT: self._debt,
            }.get(self._active_field, "")
        return self._amount_tendered

    def _set_active_value(self, value: str) -> None:
        if self._mode == MODE_MIXED:
            if self._active_field == FIELD_CASH:
                self._cash = value
            elif self._active_field == FIELD_MOBILE:
                self._mobile = value
            elif self._active_field == FIELD_VOUCHER:
                self._voucher = value
            elif self._active_field == FIELD_DEBT:
                self._debt = value
            elif self._active_field == FIELD_TENDERED:
                self._amount_tendered = value
                self._tendered_explicit = True
        else:
            self._amount_tendered = value

    def _on_keypad(self, value: str) -> None:
        self._set_active_value(value)
        self._refresh_ui()

    def _field_title(self) -> str:
        if self._partial_cb and self._partial_cb.isChecked():
            return t("Montant payé")
        return {
            FIELD_TENDERED: t("Montant reçu"),
            FIELD_CASH: t("Part espèces"),
            FIELD_MOBILE: t("Part Orange Money"),
            FIELD_VOUCHER: t("Part Moov Money"),
            FIELD_DEBT: t("Part dette"),
        }.get(self._active_field, t("Montant"))

    def _build_input(self) -> PaymentInput:
        tendered = self._parse(self._amount_tendered) if self._tendered_explicit else None
        if self._mode == MODE_CASH and not self._tendered_explicit:
            tendered = None
        return PaymentInput(
            mode=self._mode,
            amount_tendered=tendered,
            cash_amount=self._parse(self._cash),
            mobile_money_amount=self._parse(self._mobile),
            voucher_amount=self._parse(self._voucher),
            debt_amount=self._parse(self._debt),
            tendered_explicit=self._tendered_explicit,
        )

    def _refresh_ui(self) -> None:
        self._keypad.set_value(self._active_value())
        self._keypad.set_title(self._field_title())
        for field, chip in self._mixed_chips.items():
            val = {
                FIELD_CASH: self._cash,
                FIELD_MOBILE: self._mobile,
                FIELD_VOUCHER: self._voucher,
                FIELD_DEBT: self._debt,
                FIELD_TENDERED: self._amount_tendered if self._tendered_explicit else "—",
            }.get(field, "")
            amt = self._parse(val)
            base = self._mixed_labels.get(field, "")
            suffix = format_money(amt, self.currency) if amt > 0 or val not in ("", "—") else val or "0"
            chip.setText(f"{base} : {suffix}")
            chip.setStyleSheet("font-weight: 700;" if field == self._active_field else "")
        partial = self._partial_cb and self._partial_cb.isChecked()
        try:
            if partial:
                pay = self._parse(self._amount_tendered)
                change = 0.0
                if self._mode == MODE_CASH and pay > 0:
                    br = simple_pay(self.total, MODE_CASH, pay, pay)
                    change = br.change_amount
                self._change_label.setText(
                    f"{t('Partiel')} : {format_money(pay, self.currency)}"
                    + (f" — {t('Monnaie')} : {format_money(change, self.currency)}" if change else "")
                )
                self._keypad.set_confirm_enabled(pay > 0)
            else:
                inp = self._build_input()
                change = preview_change(self.total, inp)
                if self._mode == MODE_CASH:
                    self._change_label.setText(
                        f"{t('Monnaie')} : {format_money(change, self.currency)}"
                    )
                elif self._mode == MODE_MIXED and change > 0:
                    self._change_label.setText(
                        f"{t('Monnaie espèces')} : {format_money(change, self.currency)}"
                    )
                else:
                    self._change_label.setText("")
                validate(self.total, inp)
                self._keypad.set_confirm_enabled(True)
                self._error.setText("")
        except ValueError as exc:
            self._error.setText(str(exc))
            self._keypad.set_confirm_enabled(False)
        show_client = self._mode == MODE_DEBT or (
            self._mode == MODE_MIXED and self._parse(self._debt) > 0
        ) or (partial and self._debt_rest_cb and self._debt_rest_cb.isChecked())
        self._client_row.setVisible(show_client)

    def _confirm(self) -> None:
        partial = self._partial_cb and self._partial_cb.isChecked()
        debt_rest = partial and self._debt_rest_cb and self._debt_rest_cb.isChecked()
        client_id = self.client_search.client_id
        try:
            if partial:
                pay = self._parse(self._amount_tendered)
                if pay <= 0:
                    raise ValueError(t("Montant invalide"))
                if debt_rest and not client_id:
                    raise ValueError(t("Sélectionnez un client pour la dette."))
                mode = self._mode if self._mode != MODE_MIXED else MODE_CASH
                br = simple_pay(
                    self.total,
                    mode,
                    pay,
                    self._parse(self._amount_tendered) if mode == MODE_CASH else pay,
                )
                self.result_data = MaquisPaymentResult(
                    breakdown=br,
                    change_amount=br.change_amount,
                    debt_client_id=client_id,
                    partial_with_debt_remainder=debt_rest,
                )
            else:
                inp = self._build_input()
                br = validate(self.total, inp)
                if br.debt_amount > 0 or self._mode == MODE_DEBT:
                    if not client_id:
                        raise ValueError(t("Sélectionnez un client pour la dette."))
                self.result_data = MaquisPaymentResult(
                    breakdown=br,
                    change_amount=br.change_amount,
                    debt_client_id=client_id,
                )
            self.accept()
        except ValueError as exc:
            self._error.setText(str(exc))
