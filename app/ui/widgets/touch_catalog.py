"""Catalogue tactile (style tablette) : catégories en onglets, produits en tuiles.

Ce composant est partagé par la caisse et l'écran de commande des tables :
la saisie des produits est ainsi identique dans les deux écrans de Maquis Caisse.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.controllers.category_controller import CategoryController
from app.controllers.product_controller import ProductController
from app.i18n import t
from app.services import catalog_features, settings_service
from app.utils.helpers import format_money, format_quantity

# Nombre maximum de tuiles rendues d'un coup (au-delà : affiner la recherche).
MAX_TILES = 240

TILE_WIDTH = 176
TILE_HEIGHT = 132
TILE_HEIGHT_IMAGE = 206


class ProductTile(QFrame):
    """Grande tuile tactile : nom, prix, stock (et image si activée)."""

    activated = Signal(int)

    def __init__(self, product, currency: str, available: float, *, with_image: bool):
        super().__init__()
        self.product_id = int(product.id)
        self.stock_quantity = float(product.quantity or 0)
        self._unit = str(getattr(product, "unit_name", "") or "").strip()
        self._selected = False
        self.setObjectName("TouchTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(TILE_WIDTH, TILE_HEIGHT_IMAGE if with_image else TILE_HEIGHT)
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(4)
        if with_image:
            image = QLabel()
            image.setFixedHeight(84)
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setStyleSheet(
                "background: #f1f5f9; border-radius: 8px; color: #94a3b8;"
            )
            path = str(getattr(product, "image_path", "") or "")
            pixmap = QPixmap(path) if path else QPixmap()
            if not pixmap.isNull():
                image.setPixmap(
                    pixmap.scaled(
                        TILE_WIDTH - 24,
                        84,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                image.setText("•")
            box.addWidget(image)
        name = QLabel(product.name)
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet("font-size: 15px; font-weight: 700; color: #0f172a;")
        box.addWidget(name, 1)
        if getattr(product, "free_amount_sale", False):
            price_text = (
                f"réf. {format_money(product.sale_price, currency)}"
                if float(product.sale_price or 0) > 0
                else t("montant libre")
            )
        else:
            price_text = format_money(product.sale_price, currency)
        price = QLabel(price_text)
        price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        price.setStyleSheet("font-size: 17px; font-weight: 800; color: #1d4ed8;")
        box.addWidget(price)
        self._stock_label = QLabel("")
        self._stock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._stock_label)
        self.set_available(available)
        self._apply_style()

    def set_available(self, available: float) -> None:
        """Met à jour le stock affiché (panier / ardoises déjà engagées)."""
        self._stock_label.setText(
            f"{format_quantity(available)} {self._unit}".strip()
        )
        colour = "#dc2626" if available <= 0 else "#64748b"
        self._stock_label.setStyleSheet(f"font-size: 12px; color: {colour};")

    def _apply_style(self) -> None:
        border = "2px solid #2563eb" if self._selected else "1px solid #dbe3ec"
        background = "#eff6ff" if self._selected else "#ffffff"
        self.setStyleSheet(
            "#TouchTile {"
            f" border: {border}; border-radius: 12px; background: {background};"
            "}"
            "#TouchTile:hover { border: 2px solid #60a5fa; }"
        )

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_style()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        self.activated.emit(self.product_id)
        super().mousePressEvent(event)


class TouchCatalog(QFrame):
    """Panneau gauche tactile : recherche, catégories, tuiles produits."""

    product_activated = Signal(int)
    product_selected = Signal(int)
    barcode_scanned = Signal(str)

    def __init__(self, *, title: str = "", show_barcode: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._selected_product_id: Optional[int] = None
        self._category_id: Optional[int] = None
        self._tiles: List[ProductTile] = []
        self._stock_adjustments: Dict[int, float] = {}
        self._columns = 3
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        if title:
            heading = QLabel(title)
            heading.setObjectName("PageTitle")
            layout.addWidget(heading)
        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText(t("pos.barcode"))
        self.barcode_input.setMinimumHeight(44)
        self.barcode_input.returnPressed.connect(self._emit_barcode)
        self.barcode_input.setVisible(show_barcode)
        layout.addWidget(self.barcode_input)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("pos.search_product"))
        self.search_input.setMinimumHeight(48)
        self.search_input.setStyleSheet("font-size: 16px;")
        self.search_input.textChanged.connect(self.reload_products)
        layout.addWidget(self.search_input)
        self._chips_scroll = QScrollArea()
        self._chips_scroll.setWidgetResizable(True)
        self._chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chips_scroll.setFixedHeight(62)
        self._chips_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        chips_host = QWidget()
        self._chips_layout = QHBoxLayout(chips_host)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(8)
        self._chips_scroll.setWidget(chips_host)
        layout.addWidget(self._chips_scroll)
        self._grid_scroll = QScrollArea()
        self._grid_scroll.setWidgetResizable(True)
        self._grid_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(2, 2, 2, 2)
        self._grid.setSpacing(10)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._grid_scroll.setWidget(self._grid_host)
        self._grid_scroll.viewport().installEventFilter(self)
        layout.addWidget(self._grid_scroll, 1)
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(self._hint)

    # --- API ---------------------------------------------------------------
    def refresh(self) -> None:
        self.reload_categories()
        self.reload_products()

    def set_stock_adjustments(self, adjustments: Dict[int, float]) -> None:
        """Quantités à retrancher du stock affiché (panier / ardoises ouvertes).

        Les tuiles déjà affichées sont mises à jour sur place : pas de
        reconstruction de la grille à chaque article ajouté.
        """
        self._stock_adjustments = {int(k): float(v) for k, v in adjustments.items()}
        for tile in self._tiles:
            tile.set_available(
                tile.stock_quantity - self._stock_adjustments.get(tile.product_id, 0.0)
            )

    def selected_product_id(self) -> Optional[int]:
        return self._selected_product_id

    def focus_search(self) -> None:
        self.search_input.setFocus()

    def clear_search(self) -> None:
        self.search_input.clear()

    # --- Catégories --------------------------------------------------------
    def reload_categories(self) -> None:
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        categories = CategoryController.list()
        known = {None} | {category.id for category in categories}
        if self._category_id not in known:
            self._category_id = None
        self._make_chip(t("common.all"), None)
        for category in categories:
            chip = self._make_chip(category.name, category.id)
            description = (category.description or "").strip()
            if description:
                chip.setToolTip(description)
        self._chips_layout.addStretch(1)

    def _make_chip(self, label: str, category_id: Optional[int]) -> QToolButton:
        chip = QToolButton()
        chip.setText(label)
        chip.setCheckable(True)
        chip.setChecked(category_id == self._category_id)
        chip.setMinimumHeight(46)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setStyleSheet(
            "QToolButton {"
            " padding: 8px 18px; border-radius: 22px; border: 1px solid #cbd5e1;"
            " background: #f8fafc; font-size: 15px; font-weight: 600;"
            "}"
            "QToolButton:checked {"
            " background: #2563eb; color: #ffffff; border-color: #2563eb;"
            "}"
        )
        chip.clicked.connect(lambda _=False, cid=category_id: self._select_category(cid))
        self._chips_layout.addWidget(chip)
        return chip

    def _select_category(self, category_id: Optional[int]) -> None:
        self._category_id = category_id
        self.reload_categories()
        self.reload_products()

    # --- Produits ----------------------------------------------------------
    def reload_products(self) -> None:
        products = ProductController.list(
            search=self.search_input.text().strip(),
            category_id=self._category_id,
        )
        currency = settings_service.get_currency()
        with_image = catalog_features.product_images_enabled()
        self._clear_tiles()
        shown = products[:MAX_TILES]
        for index, product in enumerate(shown):
            available = float(product.quantity) - self._stock_adjustments.get(
                int(product.id), 0.0
            )
            tile = ProductTile(product, currency, available, with_image=with_image)
            tile.activated.connect(self._on_tile_activated)
            self._tiles.append(tile)
            self._grid.addWidget(tile, index // self._columns, index % self._columns)
        if not products:
            self._hint.setText(t("Aucun produit ne correspond à la recherche."))
        elif len(products) > len(shown):
            self._hint.setText(
                t("{shown} produits affichés sur {total} — affinez la recherche.").format(
                    shown=len(shown), total=len(products)
                )
            )
        else:
            self._hint.setText(
                t("Touchez un produit pour l'ajouter. Touchez la quantité pour la corriger.")
            )
        if self._selected_product_id is not None:
            self._highlight(self._selected_product_id)

    def _clear_tiles(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._tiles = []

    def _on_tile_activated(self, product_id: int) -> None:
        self._selected_product_id = int(product_id)
        self._highlight(product_id)
        self.product_selected.emit(int(product_id))
        self.product_activated.emit(int(product_id))

    def _highlight(self, product_id: int) -> None:
        for tile in self._tiles:
            tile.set_selected(tile.product_id == int(product_id))

    def _emit_barcode(self) -> None:
        code = self.barcode_input.text().strip()
        self.barcode_input.clear()
        if code:
            self.barcode_scanned.emit(code)

    # --- Disposition -------------------------------------------------------
    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (API Qt)
        if event.type() == QEvent.Type.Resize and watched is self._grid_scroll.viewport():
            self._relayout_for_width(watched.width())
        return super().eventFilter(watched, event)

    def _relayout_for_width(self, width: int) -> None:
        columns = max(1, int((width - 8) // (TILE_WIDTH + 10)))
        if columns == self._columns:
            return
        self._columns = columns
        for index, tile in enumerate(self._tiles):
            self._grid.addWidget(tile, index // columns, index % columns)
