"""Dialogue de création / modification d'un produit."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
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
        self.setMinimumWidth(500)
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
        self.pack_content = self._qty_spin()
        self.quantity = self._qty_spin()
        self.min_stock = self._qty_spin()
        self.free_amount_sale = QCheckBox("Vente : montant libre")
        self.free_amount_sale.setToolTip(
            "Le caissier saisit un montant (ex. 300 F) au lieu d'une quantité. "
            "Le prix de vente sert à estimer la marge."
        )
        self.free_hint = QLabel(
            "Exemple poissonnerie : achat 10 000 F/carton, contenu 10 kg, "
            "vente 1 500 F/kg → à la caisse on saisit « 300 F »."
        )
        self.free_hint.setWordWrap(True)
        self.free_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        self.free_amount_sale.toggled.connect(self._toggle_free_mode)
        self.is_active = QCheckBox("Produit actif")
        self.is_active.setChecked(True)

        form.addRow("Nom *", self.name)
        form.addRow("Catégorie", self.category)
        form.addRow("Code-barres", self.barcode)
        form.addRow("Référence", self.reference)
        form.addRow("Prix d'achat (ex. F / carton)", self.purchase_price)
        form.addRow("Contenu estimatif (ex. kg / carton)", self.pack_content)
        form.addRow("Prix de vente (ex. F / kg)", self.sale_price)
        form.addRow("Prix minimum", self.min_price)
        form.addRow("Stock (ex. cartons)", self.quantity)
        form.addRow("Stock minimum", self.min_stock)
        form.addRow("Unité de stock", self.unit)
        form.addRow("Mode de vente", self.free_amount_sale)
        form.addRow("", self.free_hint)
        form.addRow("Statut", self.is_active)
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
        self._toggle_free_mode(self.free_amount_sale.isChecked())

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

    def _toggle_free_mode(self, enabled: bool) -> None:
        self.free_hint.setVisible(bool(enabled))
        self.pack_content.setEnabled(bool(enabled) or self.pack_content.value() > 0)

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
        self.pack_content.setValue(float(getattr(product, "pack_content", 0) or 0))
        self.quantity.setValue(float(product.quantity))
        self.min_stock.setValue(float(product.min_stock))
        self.free_amount_sale.setChecked(bool(getattr(product, "free_amount_sale", False)))
        self.is_active.setChecked(bool(product.is_active))

    def _save(self) -> None:
        if not self.name.text().strip():
            warn(self, "Le nom du produit est obligatoire.")
            return
        if self.free_amount_sale.isChecked():
            if self.sale_price.value() <= 0:
                warn(
                    self,
                    "En montant libre, le prix de vente (référence / kg) est obligatoire "
                    "pour estimer la marge.",
                )
                return
            if self.pack_content.value() <= 0:
                warn(
                    self,
                    "Indiquez le contenu estimatif (ex. 10 kg par carton) pour convertir "
                    "le stock et estimer le coût.",
                )
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
            "pack_content": self.pack_content.value(),
            "quantity": self.quantity.value(),
            "min_stock": self.min_stock.value(),
            "free_amount_sale": self.free_amount_sale.isChecked(),
            "is_active": self.is_active.isChecked(),
        }
        self.accept()
