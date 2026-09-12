"""Dialogue de création / modification d'un produit."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app import config
from app.controllers.category_controller import CategoryController
from app.controllers.unit_controller import UnitController
from app.i18n import t
from app.services import catalog_features
from app.ui.widgets.helpers import warn


class ProductDialog(QDialog):
    """Formulaire complet d'un produit (utilisé pour l'ajout et l'édition)."""

    def __init__(self, product=None, parent=None):
        super().__init__(parent)
        self.product = product
        self.setWindowTitle(t("pos.product"))
        self.setModal(True)
        self.setMinimumWidth(520)
        self.data: Optional[dict] = None
        self._image_path = ""

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

        # Image produit (utile quand le catalogue images est activé).
        self._image_preview = QLabel(t("product.no_image"))
        self._image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_preview.setFixedSize(120, 120)
        self._image_preview.setStyleSheet(
            "border: 1px dashed #cbd5e1; border-radius: 8px; color: #94a3b8;"
        )
        self._image_preview.setScaledContents(False)
        img_btns = QHBoxLayout()
        pick = QPushButton(t("product.choose_image"))
        pick.clicked.connect(self._pick_image)
        clear = QPushButton(t("product.clear_image"))
        clear.clicked.connect(self._clear_image)
        img_btns.addWidget(pick)
        img_btns.addWidget(clear)
        img_wrap = QVBoxLayout()
        img_wrap.addWidget(self._image_preview, alignment=Qt.AlignmentFlag.AlignLeft)
        img_wrap.addLayout(img_btns)
        form.addRow(t("product.image"), img_wrap)
        # Toujours permettre d'attacher une image ; la grille POS dépend du réglage.
        show_images = catalog_features.product_images_enabled()
        self._image_preview.setVisible(True)
        pick.setToolTip(
            t("settings.catalog_images_tip")
            if show_images
            else "Activez « produits avec images » dans Paramètres pour l'afficher en caisse."
        )

        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self.reject)
        save = QPushButton(t("common.save"))
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

    def _show_image_preview(self, path: str) -> None:
        if path and Path(path).is_file():
            pix = QPixmap(path)
            if not pix.isNull():
                self._image_preview.setPixmap(
                    pix.scaled(
                        116,
                        116,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._image_preview.setText("")
                return
        self._image_preview.setPixmap(QPixmap())
        self._image_preview.setText(t("product.no_image"))

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("product.choose_image"),
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        config.ensure_directories()
        src = Path(path)
        dest = config.PRODUCT_IMAGE_DIR / f"{uuid.uuid4().hex}{src.suffix.lower()}"
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            warn(self, str(exc))
            return
        self._image_path = str(dest)
        self._show_image_preview(self._image_path)

    def _clear_image(self) -> None:
        self._image_path = ""
        self._show_image_preview("")

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
        self._image_path = str(getattr(product, "image_path", "") or "")
        self._show_image_preview(self._image_path)

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
            "image_path": self._image_path,
            "is_active": self.is_active.isChecked(),
        }
        self.accept()
