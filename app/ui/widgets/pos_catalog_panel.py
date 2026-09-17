"""Catalogue caisse (grille + chips) — partagé POS et commandes table Maquis."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.controllers.product_controller import ProductController
from app.i18n import t
from app.services import catalog_features, product_profile, settings_service
from app.ui.responsive import LayoutProfile
from app.ui.theme import MAQUIS_PRIMARY, PRIMARY
from app.ui.widgets.helpers import page_title, warn
from app.utils.helpers import format_money, format_quantity


class PosCatalogPanel(QFrame):
    """Sélection produits : identique POS / tablette (chips + grille ou liste)."""

    product_chosen = Signal(object)

    def __init__(self, parent: QWidget | None = None, *, show_pos_title: bool = True):
        super().__init__(parent)
        self.setObjectName("Card")
        self._maquis = product_profile.is_maquis()
        self._accent = MAQUIS_PRIMARY if self._maquis else PRIMARY
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        if show_pos_title:
            layout.addWidget(page_title(t("pos.title")))
        search_row = QHBoxLayout()
        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText(t("pos.barcode"))
        self.barcode_input.returnPressed.connect(self._add_by_barcode)
        search_row.addWidget(self.barcode_input)
        self._barcode_row = QWidget()
        self._barcode_row.setLayout(search_row)
        layout.addWidget(self._barcode_row)
        if self._maquis:
            self._barcode_row.setVisible(False)
        filter_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("pos.search_product"))
        self.search_input.textChanged.connect(self._reload_products)
        self.category_filter = QComboBox()
        self.category_filter.currentIndexChanged.connect(self._reload_products)
        filter_row.addWidget(self.search_input, 3)
        filter_row.addWidget(self.category_filter, 2)
        layout.addLayout(filter_row)
        self.category_chips_scroll = QScrollArea()
        self.category_chips_scroll.setWidgetResizable(True)
        self.category_chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.category_chips_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.category_chips_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.category_chips_scroll.setFixedHeight(56)
        self.category_chips_host = QWidget()
        self.category_chips_layout = QHBoxLayout(self.category_chips_host)
        self.category_chips_layout.setContentsMargins(0, 0, 0, 0)
        self.category_chips_layout.setSpacing(8)
        self.category_chips_layout.addStretch(1)
        self.category_chips_scroll.setWidget(self.category_chips_host)
        layout.addWidget(self.category_chips_scroll)
        self.product_table = QTableWidget(0, 3)
        self.product_table.setHorizontalHeaderLabels(
            [t("pos.product"), t("pos.price"), t("pos.stock")]
        )
        self.product_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.product_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.product_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.product_table.doubleClicked.connect(self._add_selected_product)
        layout.addWidget(self.product_table)
        self.product_grid_scroll = QScrollArea()
        self.product_grid_scroll.setWidgetResizable(True)
        self.product_grid_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.product_grid_host = QWidget()
        self.product_grid_layout = QGridLayout(self.product_grid_host)
        self.product_grid_layout.setContentsMargins(4, 4, 4, 4)
        self.product_grid_layout.setSpacing(10)
        self.product_grid_scroll.setWidget(self.product_grid_host)
        layout.addWidget(self.product_grid_scroll)
        self.add_to_cart_btn = QPushButton(t("pos.add_to_cart"))
        self.add_to_cart_btn.setObjectName("Primary")
        self.add_to_cart_btn.clicked.connect(self._add_selected_product)
        layout.addWidget(self.add_to_cart_btn)
        self._chip_buttons: list[QToolButton] = []
        self._grid_product_ids: list[int] = []
        self._on_before_add: Optional[Callable[[object], bool]] = None
        self._apply_catalog_mode()
        self._reload_categories()
        self._reload_products()

    def set_before_add_hook(self, hook: Optional[Callable[[object], bool]]) -> None:
        """Si le hook retourne False, l'ajout est annulé (ex. stock panier POS)."""
        self._on_before_add = hook

    def refresh(self) -> None:
        self._apply_catalog_mode()
        self._reload_categories()
        self._reload_products()
        self._apply_large_text()

    def selected_product(self):
        row = self.product_table.currentRow()
        if row >= 0:
            item = self.product_table.item(row, 0)
            if item is not None:
                pid = item.data(Qt.ItemDataRole.UserRole)
                return ProductController.get(pid) if pid else None
        return None

    def _apply_catalog_mode(self) -> None:
        use_chips = catalog_features.category_browser_enabled()
        use_images = catalog_features.product_images_enabled()
        self.category_filter.setVisible(not use_chips)
        self.category_chips_scroll.setVisible(use_chips)
        self.product_table.setVisible(not use_images)
        self.product_grid_scroll.setVisible(use_images)
        # Tablette Maquis : tap carte = ajout (pas de bouton « Ajouter »)
        self.add_to_cart_btn.setVisible(not use_images and not self._maquis)
        if self._maquis:
            self._barcode_row.setVisible(False)

    def _reload_categories(self) -> None:
        from app.controllers.category_controller import CategoryController

        current = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem(t("pos.all_categories"), None)
        categories = CategoryController.list()
        for category in categories:
            self.category_filter.addItem(category.name, category.id)
        index = self.category_filter.findData(current)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)
        self._rebuild_category_chips(categories, current)

    def _rebuild_category_chips(self, categories, current) -> None:
        while self.category_chips_layout.count():
            item = self.category_chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._chip_buttons = []

        def make_chip(label: str, cat_id):
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setChecked(cat_id == current)
            btn.setMinimumHeight(40)
            btn.setStyleSheet(
                "QToolButton { padding: 6px 14px; border-radius: 18px; "
                "border: 1px solid #cbd5e1; background: #f8fafc; }"
                f"QToolButton:checked {{ background: {self._accent}; color: white; "
                f"border-color: {self._accent}; }}"
            )
            btn.clicked.connect(lambda _=False, cid=cat_id: self._select_category_chip(cid))
            self.category_chips_layout.addWidget(btn)
            self._chip_buttons.append(btn)

        make_chip(t("pos.all_categories"), None)
        for category in categories:
            make_chip(category.name, category.id)
        self.category_chips_layout.addStretch(1)

    def _select_category_chip(self, category_id) -> None:
        self.category_filter.blockSignals(True)
        index = self.category_filter.findData(category_id)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)
        from app.controllers.category_controller import CategoryController

        self._rebuild_category_chips(CategoryController.list(), category_id)
        self._reload_products()

    def _clear_product_grid(self) -> None:
        while self.product_grid_layout.count():
            item = self.product_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._grid_product_ids = []

    def _make_product_card(self, product, currency: str) -> QFrame:
        card = QFrame()
        card.setObjectName("ProductCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedSize(148, 180)
        card.setStyleSheet(
            "#ProductCard { border: 1px solid #e2e8f0; border-radius: 10px; "
            "background: #ffffff; }"
            f"#ProductCard:hover {{ border: 2px solid {self._accent}; }}"
        )
        box = QVBoxLayout(card)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(4)
        img = QLabel()
        img.setFixedSize(128, 96)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setStyleSheet("background: #f1f5f9; border-radius: 6px; color: #94a3b8;")
        path = str(getattr(product, "image_path", "") or "")
        pix = QPixmap(path) if path else QPixmap()
        if not pix.isNull():
            img.setPixmap(
                pix.scaled(
                    128,
                    96,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            img.setText("•")
        box.addWidget(img, alignment=Qt.AlignmentFlag.AlignCenter)
        name = QLabel(product.name)
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet("font-weight: 600; font-size: 12px;")
        box.addWidget(name)
        if getattr(product, "free_amount_sale", False):
            price_txt = (
                f"réf. {format_money(product.sale_price, currency)}"
                if float(product.sale_price or 0) > 0
                else "montant libre"
            )
        else:
            price_txt = format_money(product.sale_price, currency)
        price = QLabel(price_txt)
        price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        price.setStyleSheet("color: #0f172a; font-weight: 700;")
        box.addWidget(price)
        pid = product.id

        def _click(_event=None, product_id=pid):
            product_obj = ProductController.get(product_id)
            if product_obj:
                self._emit_product(product_obj)

        card.mousePressEvent = _click
        return card

    def _reload_products(self) -> None:
        products = ProductController.list(
            search=self.search_input.text().strip(),
            category_id=self.category_filter.currentData(),
        )
        currency = settings_service.get_currency()
        self.product_table.setRowCount(len(products))
        for row, product in enumerate(products):
            label = product.name
            if getattr(product, "free_amount_sale", False):
                label = f"{product.name} · montant libre"
            name_item = QTableWidgetItem(label)
            name_item.setData(Qt.ItemDataRole.UserRole, product.id)
            self.product_table.setItem(row, 0, name_item)
            if getattr(product, "free_amount_sale", False):
                price_txt = (
                    f"réf. {format_money(product.sale_price, currency)}/kg"
                    if float(product.sale_price or 0) > 0
                    else "montant libre"
                )
            else:
                price_txt = format_money(product.sale_price, currency)
            self.product_table.setItem(row, 1, QTableWidgetItem(price_txt))
            stock_item = QTableWidgetItem(
                f"{format_quantity(product.quantity)} {product.unit_name}".strip()
            )
            if product.is_out_of_stock:
                stock_item.setForeground(Qt.GlobalColor.red)
            self.product_table.setItem(row, 2, stock_item)
        self._clear_product_grid()
        cols = 3
        for index, product in enumerate(products):
            card = self._make_product_card(product, currency)
            self.product_grid_layout.addWidget(card, index // cols, index % cols)
            self._grid_product_ids.append(product.id)
        self.product_grid_layout.setRowStretch((len(products) + cols - 1) // cols, 1)
        self._apply_large_text()

    def _add_by_barcode(self) -> None:
        code = self.barcode_input.text().strip()
        if not code:
            return
        product = ProductController.find_by_barcode(code)
        self.barcode_input.clear()
        if not product:
            warn(self, f'Aucun produit avec le code-barres « {code} ».')
            return
        self._emit_product(product)

    def _add_selected_product(self) -> None:
        product = self.selected_product()
        if product:
            self._emit_product(product)

    def _emit_product(self, product) -> None:
        if self._on_before_add is not None and not self._on_before_add(product):
            return
        self.product_chosen.emit(product)

    def _apply_large_text(self) -> None:
        large = settings_service.get_setting("pos_catalog_large_text", "0") == "1"
        size_key = settings_service.get_setting("pos_catalog_text_size", "large")
        if large:
            pt = 22 if size_key == "xlarge" else 18
            row_h = 46 if size_key == "xlarge" else 38
        else:
            pt = 14
            row_h = 30
        font = QFont()
        font.setPointSize(pt)
        font.setBold(large)
        price_font = QFont(font)
        if large:
            price_font.setPointSize(pt + 2)
        self.product_table.setFont(font)
        self.product_table.verticalHeader().setDefaultSectionSize(row_h)
        self.product_table.verticalHeader().setVisible(False)
        for row in range(self.product_table.rowCount()):
            item = self.product_table.item(row, 1)
            if item is not None:
                item.setFont(price_font)

    def apply_layout_profile(self, profile: LayoutProfile) -> None:
        """Ajuste la grille produits selon la largeur (comme la tablette)."""
        cols = 2 if profile.content_width < 700 or profile.stack_panels else 3
        if profile.content_width >= 1100:
            cols = 4
        # Rebuild grid with new column count when needed
        products = ProductController.list(
            search=self.search_input.text().strip(),
            category_id=self.category_filter.currentData(),
        )
        if not catalog_features.product_images_enabled():
            return
        currency = settings_service.get_currency()
        self._clear_product_grid()
        for index, product in enumerate(products):
            card = self._make_product_card(product, currency)
            self.product_grid_layout.addWidget(card, index // cols, index % cols)
            self._grid_product_ids.append(product.id)
        self.product_grid_layout.setRowStretch((len(products) + cols - 1) // cols, 1)
