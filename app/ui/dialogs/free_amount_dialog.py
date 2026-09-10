"""Dialogue de saisie d'un montant libre (vente au montant demandé)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.services import settings_service
from app.utils.helpers import format_money


QUICK_AMOUNTS = (100, 200, 300, 500, 1000, 3600)


class FreeAmountDialog(QDialog):
    """Le caissier choisit le montant demandé par le client (ex. 300 F)."""

    def __init__(self, product_name: str, sale_price: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Montant — {product_name}")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.amount: Optional[float] = None
        self.currency = settings_service.get_currency()
        self.sale_price = float(sale_price or 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel(product_name)
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        if self.sale_price > 0:
            hint = QLabel(
                f"Prix de référence : {format_money(self.sale_price, self.currency)} / unité\n"
                "Saisissez le montant demandé par le client."
            )
        else:
            hint = QLabel("Saisissez le montant demandé par le client.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #64748b;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setSpacing(8)
        for index, value in enumerate(QUICK_AMOUNTS):
            button = QPushButton(format_money(value, self.currency))
            button.setMinimumHeight(44)
            button.clicked.connect(lambda _=False, v=value: self._choose(v))
            grid.addWidget(button, index // 3, index % 3)
        layout.addLayout(grid)

        other_row = QHBoxLayout()
        other_row.addWidget(QLabel("Autre montant :"))
        self.custom = QDoubleSpinBox()
        self.custom.setRange(0, 1_000_000_000)
        self.custom.setDecimals(0)
        self.custom.setSingleStep(50)
        self.custom.setSuffix(f" {self.currency}")
        other_row.addWidget(self.custom, 1)
        layout.addLayout(other_row)

        self.estimate = QLabel("")
        self.estimate.setStyleSheet("color: #64748b; font-size: 12px;")
        self.estimate.setWordWrap(True)
        layout.addWidget(self.estimate)
        self.custom.valueChanged.connect(self._update_estimate)
        self._update_estimate()

        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Ajouter")
        self.ok.setObjectName("Success")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self._confirm_custom)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(self.ok)
        layout.addLayout(buttons)
        self._refresh_ok()

    def _refresh_ok(self) -> None:
        self.ok.setEnabled(float(self.custom.value()) > 0)

    def _update_estimate(self) -> None:
        amount = float(self.custom.value())
        self._refresh_ok()
        if amount <= 0 or self.sale_price <= 0:
            self.estimate.setText(
                "Saisissez un montant ou choisissez un raccourci ci-dessus."
                if amount <= 0
                else ""
            )
            return
        qty = amount / self.sale_price
        self.estimate.setText(
            f"Quantité estimée : {qty:g} unité(s) de vente "
            f"({format_money(amount, self.currency)} ÷ "
            f"{format_money(self.sale_price, self.currency)})"
        )

    def _choose(self, value: float) -> None:
        self.amount = float(value)
        self.accept()

    def _confirm_custom(self) -> None:
        value = float(self.custom.value())
        if value <= 0:
            from app.ui.widgets.helpers import warn

            warn(self, "Saisissez un montant supérieur à 0 pour continuer.")
            self.custom.setFocus()
            return
        self.amount = value
        self.accept()
