"""Composition rapide d'un plat de base + accessoires à prix fixe (Maquis)."""
from __future__ import annotations
from PySide6.QtWidgets import QCheckBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from app.i18n import t
from app.ui.widgets.helpers import dialog_header_banner
from app.utils.helpers import format_money


class AccessoryPickerDialog(QDialog):
    """Clic sur un plat « Poisson braisé » -> coche attiéké/alloco/frites -> une
    seule ligne de ticket au prix additionné. Le plat seul (sans rien coché)
    reste possible — on valide simplement sans rien cocher."""

    def __init__(self, product_name: str, base_price: float, accessories: list[dict], currency: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(product_name)
        self.setModal(True)
        self.setMinimumWidth(360)
        self._base_price = float(base_price)
        self._currency = currency
        self.selected: list[dict] = []
        self.quantity = 1.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(dialog_header_banner(product_name, format_money(self._base_price, currency)))
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 20)
        outer.addLayout(layout, 1)

        self._checks: list[tuple[QCheckBox, dict]] = []
        for item in accessories:
            box = QCheckBox(f"{item['name']} (+{format_money(float(item['price']), currency)})")
            box.toggled.connect(self._update_total)
            layout.addWidget(box)
            self._checks.append((box, item))

        qty_row = QHBoxLayout()
        qty_row.addWidget(QLabel(t('Quantité')))
        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(1, 999)
        self.qty_spin.setDecimals(0)
        self.qty_spin.setValue(1)
        self.qty_spin.valueChanged.connect(self._update_total)
        qty_row.addWidget(self.qty_spin)
        qty_row.addStretch(1)
        layout.addLayout(qty_row)

        self.total_label = QLabel('')
        self.total_label.setStyleSheet('font-weight: 700; font-size: 15px;')
        layout.addWidget(self.total_label)

        buttons = QHBoxLayout()
        cancel = QPushButton(t('common.cancel'))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(t('Ajouter au panier'))
        ok.setObjectName('Primary')
        ok.setDefault(True)
        ok.clicked.connect(self._confirm)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(ok)
        layout.addLayout(buttons)

        self._update_total()

    def _unit_price(self) -> float:
        extra = sum(float(item['price']) for box, item in self._checks if box.isChecked())
        return self._base_price + extra

    def _update_total(self, *_args) -> None:
        unit = self._unit_price()
        qty = self.qty_spin.value()
        self.total_label.setText(f"{t('Total')} : {format_money(unit * qty, self._currency)}")

    def _confirm(self) -> None:
        self.selected = [item for box, item in self._checks if box.isChecked()]
        self.quantity = float(self.qty_spin.value())
        self.accept()
