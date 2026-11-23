"""Dialogue de saisie d'un montant libre (vente au montant demandé)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.i18n import t
from app.services import cash_controls, settings_service
from app.utils.helpers import format_money
from app.ui.widgets.money_spin import MoneySpinBox


class FreeAmountDialog(QDialog):
    """Le caissier choisit le montant demandé par le client (ex. 300 F)."""

    def __init__(self, product_name: str, sale_price: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{t('Montant')} — {product_name}")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.amount: Optional[float] = None
        self.currency = settings_service.get_currency()
        self.sale_price = float(sale_price or 0)
        presets = cash_controls.get_free_amount_presets()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header_banner = QFrame()
        header_banner.setObjectName("DialogHeaderBanner")
        header_layout = QVBoxLayout(header_banner)
        header_layout.setContentsMargins(20, 14, 20, 16)
        header_layout.setSpacing(2)
        title = QLabel(product_name)
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title)
        if self.sale_price > 0:
            ref = QLabel(
                f"{t('Prix de référence')} : "
                f"{format_money(self.sale_price, self.currency)} / {t('unité')}"
            )
            ref.setStyleSheet("font-size: 12px;")
            ref.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_layout.addWidget(ref)
        outer.addWidget(header_banner)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        outer.addLayout(layout, 1)

        hint = QLabel(t("Saisissez le montant demandé par le client."))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #64748b;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setSpacing(8)
        if presets:
            for index, value in enumerate(presets):
                button = QPushButton(format_money(value, self.currency))
                button.setMinimumHeight(44)
                button.setObjectName("Primary")
                button.clicked.connect(lambda _=False, v=value: self._choose(v))
                grid.addWidget(button, index // 3, index % 3)
        else:
            empty = QLabel(t("Aucun raccourci configuré — saisissez un montant."))
            empty.setStyleSheet("color: #64748b;")
            grid.addWidget(empty, 0, 0)
        layout.addLayout(grid)

        custom_card = QFrame()
        custom_card.setObjectName("SmallCard")
        custom_layout = QVBoxLayout(custom_card)
        custom_layout.setContentsMargins(12, 10, 12, 10)
        custom_layout.setSpacing(6)
        other_row = QHBoxLayout()
        other_row.addWidget(QLabel(t("Autre montant :")))
        self.custom = MoneySpinBox()
        self.custom.setRange(0, 1_000_000_000)
        self.custom.setDecimals(3)
        self.custom.setSingleStep(50)
        self.custom.setSuffix(f" {self.currency}")
        other_row.addWidget(self.custom, 1)
        custom_layout.addLayout(other_row)

        self.estimate = QLabel("")
        self.estimate.setStyleSheet("color: #64748b; font-size: 12px;")
        self.estimate.setWordWrap(True)
        custom_layout.addWidget(self.estimate)
        layout.addWidget(custom_card)

        buttons = QHBoxLayout()
        cancel = QPushButton(t("Annuler"))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(t("Ajouter"))
        ok.setObjectName("Success")
        ok.setEnabled(False)
        ok.clicked.connect(self._confirm_custom)
        self.ok = ok
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(ok)
        layout.addLayout(buttons)

        self.custom.valueChanged.connect(self._update_estimate)
        self._update_estimate()

    def _update_estimate(self) -> None:
        amount = float(self.custom.value())
        self.ok.setEnabled(amount > 0)
        if amount <= 0 or self.sale_price <= 0:
            self.estimate.setText(
                t("Saisissez un montant supérieur à 0 pour continuer.")
                if amount <= 0
                else ""
            )
            return
        qty = amount / self.sale_price
        self.estimate.setText(
            f"{t('Quantité estimée')} : {qty:g} {t('unité(s) de vente')} "
            f"({format_money(amount, self.currency)} ÷ "
            f"{format_money(self.sale_price, self.currency)})"
        )

    def _choose(self, value: float) -> None:
        self.amount = float(value)
        self.accept()

    def _confirm_custom(self) -> None:
        value = float(self.custom.value())
        if value <= 0:
            return
        self.amount = value
        self.accept()
