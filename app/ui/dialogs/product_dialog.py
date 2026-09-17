"""Dialogue de création / modification d'un produit."""
from __future__ import annotations
import shutil
import uuid
from pathlib import Path
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout
from app import config
from app.controllers.category_controller import CategoryController
from app.controllers.unit_controller import UnitController
from app.i18n import t
from app.services import catalog_features, product_profile
from app.ui.widgets.helpers import warn

class ProductDialog(QDialog):
    """Formulaire complet d'un produit (utilisé pour l'ajout et l'édition)."""

    def __init__(self, product=None, parent=None):
        super().__init__(parent)
        self.product = product
        self._maquis = product_profile.is_maquis()
        self.setWindowTitle(t('pos.product'))
        self.setModal(True)
        self.setMinimumWidth(480 if self._maquis else 520)
        self.data: Optional[dict] = None
        self._image_path = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit()
        self.barcode = QLineEdit()
        self.reference = QLineEdit()
        self.category = QComboBox()
        self.category.addItem(t('— Aucune —'), None)
        for category in CategoryController.list():
            self.category.addItem(category.name, category.id)
        self.unit = QComboBox()
        self.unit.addItem(t('— Aucune —'), None)
        for unit in UnitController.list():
            self.unit.addItem(unit.name, unit.id)
        self.purchase_price = self._money_spin()
        self.sale_price = self._money_spin()
        self.min_price = self._money_spin()
        self.pack_content = self._qty_spin()
        self.quantity = self._qty_spin()
        self.min_stock = self._qty_spin()
        self.free_amount_sale = QCheckBox(t('Vente : montant libre'))
        self.free_amount_sale.setToolTip(t("Le caissier saisit un montant (ex. 300 F) au lieu d'une quantité. Le prix de vente sert à estimer la marge."))
        self.free_hint = QLabel(t('Exemple poissonnerie : achat 10 000 F/carton, contenu 10 kg, vente 1 500 F/kg → à la caisse on saisit « 300 F ».'))
        self.free_hint.setWordWrap(True)
        self.free_hint.setStyleSheet('color: #64748b; font-size: 12px;')
        self.free_amount_sale.toggled.connect(self._toggle_free_mode)
        self.is_active = QCheckBox(t('Produit actif'))
        self.is_active.setChecked(True)
        form.addRow(t('Nom *'), self.name)
        cat_row = QHBoxLayout()
        cat_row.setSpacing(8)
        cat_row.addWidget(self.category, 1)
        self._add_category_btn = QPushButton('+ ' + t('categories.new'))
        self._add_category_btn.setToolTip(t('product.add_category_tip'))
        self._add_category_btn.clicked.connect(self._add_category)
        cat_row.addWidget(self._add_category_btn)
        form.addRow(t('Catégorie'), cat_row)
        # Maquis tablette : pas de code-barres / référence boutique
        self._barcode_label = QLabel(t('Code-barres'))
        self._ref_label = QLabel(t('Référence'))
        form.addRow(self._barcode_label, self.barcode)
        form.addRow(self._ref_label, self.reference)
        if self._maquis:
            buy_label = t("Prix d'achat")
            sale_label = t('Prix de vente')
            stock_label = t('Stock')
            pack_label = t('Contenu / pack')
        else:
            buy_label = t("Prix d'achat (ex. F / carton)")
            sale_label = t('Prix de vente (ex. F / kg)')
            stock_label = t('Stock (ex. cartons)')
            pack_label = t('Contenu estimatif (ex. kg / carton)')
        form.addRow(buy_label, self.purchase_price)
        form.addRow(pack_label, self.pack_content)
        form.addRow(sale_label, self.sale_price)
        form.addRow(t('Prix minimum'), self.min_price)
        form.addRow(stock_label, self.quantity)
        form.addRow(t('Stock minimum'), self.min_stock)
        form.addRow(t('Unité de stock'), self.unit)
        form.addRow(t('Mode de vente'), self.free_amount_sale)
        form.addRow('', self.free_hint)
        form.addRow(t('Statut'), self.is_active)
        self._image_preview = QLabel(t('product.no_image'))
        self._image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_preview.setFixedSize(120, 120)
        self._image_preview.setStyleSheet('border: 1px dashed #cbd5e1; border-radius: 8px; color: #94a3b8;')
        self._image_preview.setScaledContents(False)
        img_btns = QHBoxLayout()
        self._pick_image_btn = QPushButton(t('product.upload_image'))
        self._pick_image_btn.setObjectName('Primary')
        self._pick_image_btn.clicked.connect(self._pick_image)
        clear = QPushButton(t('product.clear_image'))
        clear.clicked.connect(self._clear_image)
        img_btns.addWidget(self._pick_image_btn)
        img_btns.addWidget(clear)
        img_wrap = QVBoxLayout()
        self._image_hint = QLabel('')
        self._image_hint.setWordWrap(True)
        self._image_hint.setStyleSheet('color: #64748b; font-size: 12px;')
        img_wrap.addWidget(self._image_preview, alignment=Qt.AlignmentFlag.AlignLeft)
        img_wrap.addLayout(img_btns)
        img_wrap.addWidget(self._image_hint)
        form.addRow(t('product.image'), img_wrap)
        self._apply_catalog_feature_ui()
        if self._maquis:
            self.barcode.setVisible(False)
            self.reference.setVisible(False)
            self._barcode_label.setVisible(False)
            self._ref_label.setVisible(False)
            # Masquer aussi les labels de ligne FormLayout
            self.barcode.hide()
            self.reference.hide()
        layout.addLayout(form)
        buttons = QHBoxLayout()
        cancel = QPushButton(t('common.cancel'))
        cancel.clicked.connect(self.reject)
        save = QPushButton(t('common.save'))
        save.setObjectName('Primary')
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
        spin.setRange(0, 1000000000)
        spin.setDecimals(0)
        spin.setSingleStep(100)
        return spin

    def _qty_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 10000000)
        spin.setDecimals(3)
        spin.setSingleStep(1)
        return spin

    def _toggle_free_mode(self, enabled: bool) -> None:
        self.free_hint.setVisible(bool(enabled))
        self.pack_content.setEnabled(bool(enabled) or self.pack_content.value() > 0)

    def _apply_catalog_feature_ui(self) -> None:
        """Met en avant upload / catégorie si les options caisse sont actives."""
        images_on = catalog_features.product_images_enabled()
        cats_on = catalog_features.category_browser_enabled()
        self._add_category_btn.setVisible(True)
        if images_on:
            self._pick_image_btn.setText(t('product.upload_image'))
            self._pick_image_btn.setToolTip(t('settings.catalog_images_tip'))
            self._image_hint.setText(t('product.upload_enabled_hint'))
            self._image_preview.setStyleSheet(
                'border: 2px dashed #2563eb; border-radius: 8px; color: #64748b; background: #eff6ff;'
            )
        else:
            self._pick_image_btn.setText(t('product.choose_image'))
            self._pick_image_btn.setToolTip(t('settings.catalog_images_tip'))
            self._image_hint.setText(t('product.upload_disabled_hint'))
            self._image_preview.setStyleSheet(
                'border: 1px dashed #cbd5e1; border-radius: 8px; color: #94a3b8;'
            )
        if cats_on:
            self._add_category_btn.setToolTip(t('product.add_category_tip'))

    def _reload_categories(self, select_id: Optional[int] = None) -> None:
        current = select_id if select_id is not None else self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem(t('— Aucune —'), None)
        for category in CategoryController.list():
            self.category.addItem(category.name, category.id)
        if current is not None:
            idx = self.category.findData(current)
            if idx >= 0:
                self.category.setCurrentIndex(idx)
        self.category.blockSignals(False)

    def _add_category(self) -> None:
        from app.ui.dialogs.category_dialog import CategoryDialog

        dialog = CategoryDialog(parent=self)
        if not dialog.exec() or not dialog.data:
            return
        category = CategoryController.create(
            dialog.data['name'], dialog.data['description']
        )
        self._reload_categories(select_id=category.id)

    def _show_image_preview(self, path: str) -> None:
        if path and Path(path).is_file():
            pix = QPixmap(path)
            if not pix.isNull():
                self._image_preview.setPixmap(pix.scaled(116, 116, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self._image_preview.setText('')
                return
        self._image_preview.setPixmap(QPixmap())
        self._image_preview.setText(t('product.no_image'))

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t('product.choose_image'), '', 'Images (*.png *.jpg *.jpeg *.webp *.bmp)')
        if not path:
            return
        config.ensure_directories()
        src = Path(path)
        dest = config.PRODUCT_IMAGE_DIR / f'{uuid.uuid4().hex}{src.suffix.lower()}'
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            warn(self, str(exc))
            return
        self._image_path = str(dest)
        self._show_image_preview(self._image_path)

    def _clear_image(self) -> None:
        self._image_path = ''
        self._show_image_preview('')

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
        self.pack_content.setValue(float(getattr(product, 'pack_content', 0) or 0))
        self.quantity.setValue(float(product.quantity))
        self.min_stock.setValue(float(product.min_stock))
        self.free_amount_sale.setChecked(bool(getattr(product, 'free_amount_sale', False)))
        self.is_active.setChecked(bool(product.is_active))
        self._image_path = str(getattr(product, 'image_path', '') or '')
        self._show_image_preview(self._image_path)

    def _save(self) -> None:
        if not self.name.text().strip():
            warn(self, t('Le nom du produit est obligatoire.'))
            return
        if self.free_amount_sale.isChecked():
            if self.sale_price.value() <= 0:
                warn(self, t('En montant libre, le prix de vente (référence / kg) est obligatoire pour estimer la marge.'))
                return
            if self.pack_content.value() <= 0:
                warn(self, t('Indiquez le contenu estimatif (ex. 10 kg par carton) pour convertir le stock et estimer le coût.'))
                return
        self.data = {'name': self.name.text().strip(), 'barcode': self.barcode.text().strip(), 'reference': self.reference.text().strip(), 'category_id': self.category.currentData(), 'unit_id': self.unit.currentData(), 'purchase_price': self.purchase_price.value(), 'sale_price': self.sale_price.value(), 'min_price': self.min_price.value(), 'pack_content': self.pack_content.value(), 'quantity': self.quantity.value(), 'min_stock': self.min_stock.value(), 'free_amount_sale': self.free_amount_sale.isChecked(), 'image_path': self._image_path, 'is_active': self.is_active.isChecked()}
        self.accept()
