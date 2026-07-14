"""Dialogue de création / modification d'un produit."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.controllers.category_controller import CategoryController
from app.controllers.unit_controller import UnitController
from app.ui.widgets.helpers import warn


class ProductDialog(QDialog):
    """Formulaire complet d'un produit (utilisé pour l'ajout et l'édition)."""

    def __init__(self, product=None, parent=None):
        super().__init__(parent)
        self.product = product
        self.setWindowTitle("Produit")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.data: Optional[dict] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        form = QFormLayout()
        form.setSpacing(10)

        self.name = QLineEdit()
        self.barcode = QLineEdit()
        self.reference = QLineEdit()

        self.category = QComboBox()
        self.category.addItem("— Aucune —", None)
        for category in CategoryController.list():
            self.category.addItem(category.name, category.id)

        self.unit = QComboBox()
        self.unit.addItem("— Aucune —", None)
        for unit in UnitController.list():
            self.unit.addItem(unit.name, unit.id)

        self.purchase_price = self._money_spin()
        self.sale_price = self._money_spin()
        self.min_price = self._money_spin()
        self.quantity = self._qty_spin()
        self.min_stock = self._qty_spin()

        form.addRow("Nom *", self.name)
        form.addRow("Catégorie", self.category)
        form.addRow("Code-barres", self.barcode)
        form.addRow("Référence", self.reference)
        form.addRow("Prix d'achat", self.purchase_price)
        form.addRow("Prix de vente", self.sale_price)
        form.addRow("Prix minimum", self.min_price)
        form.addRow("Quantité", self.quantity)
        form.addRow("Stock minimum", self.min_stock)
        form.addRow("Unité", self.unit)
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

        if product:
            self._fill(product)

    def _money_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 1_000_000_000)
        spin.setDecimals(0)
        spin.setSingleStep(100)
        return spin

    def _qty_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 10_000_000)
        spin.setDecimals(3)
        spin.setSingleStep(1)
        return spin

    def _fill(self, product) -> None:
        self.name.setText(product.name)
        self.barcode.setText(product.barcode)
        self.reference.setText(product.reference)
        if product.category_id:
            idx = self.category.findData(product.category_id)
            if idx >= 0:
                self.category.setCurrentIndex(idx)
        if product.unit_id:
            idx = self.unit.findData(product.unit_id)
            if idx >= 0:
                self.unit.setCurrentIndex(idx)
        self.purchase_price.setValue(float(product.purchase_price))
        self.sale_price.setValue(float(product.sale_price))
        self.min_price.setValue(float(product.min_price))
        self.quantity.setValue(float(product.quantity))
        self.min_stock.setValue(float(product.min_stock))

    def _save(self) -> None:
        if not self.name.text().strip():
            warn(self, "Le nom du produit est obligatoire.")
            return
        self.data = {
            "name": self.name.text().strip(),
            "barcode": self.barcode.text().strip(),
            "reference": self.reference.text().strip(),
            "category_id": self.category.currentData(),
            "unit_id": self.unit.currentData(),
            "purchase_price": self.purchase_price.value(),
            "sale_price": self.sale_price.value(),
            "min_price": self.min_price.value(),
            "quantity": self.quantity.value(),
            "min_stock": self.min_stock.value(),
            "is_active": True,
        }
        self.accept()
