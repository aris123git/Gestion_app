"""Saisie tactile d'une commande Maquis depuis une table."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
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
    QVBoxLayout,
    QWidget,
)

from app.controllers.category_controller import CategoryController
from app.controllers.product_controller import ProductController
from app.services import order_service, settings_service
from app.ui.widgets.helpers import confirm, warn
from app.utils.helpers import format_money, format_quantity


class MaquisOrderDialog(QDialog):
    """Catalogue à gauche et commande de table à droite, comme la caisse."""

    def __init__(self, table, order, parent=None):
        super().__init__(parent)
        self.table = table
        self.order_id = order.id
        self.setWindowTitle(f"Commande — {table.display_name}")
        self.setMinimumSize(820, 560)
        self.resize(1100, 700)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._build_catalog(), 5)
        root.addWidget(self._build_cart(), 4)
        self._reload_categories()
        self._reload_products()
        self._reload_order()

    def _build_catalog(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel("Produits")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Rechercher un produit…")
        self.search_input.textChanged.connect(self._reload_products)
        layout.addWidget(self.search_input)
        self.category_filter = QComboBox()
        self.category_filter.currentIndexChanged.connect(self._reload_products)
        layout.addWidget(self.category_filter)
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setSpacing(10)
        self.grid_scroll.setWidget(self.grid_host)
        layout.addWidget(self.grid_scroll, 1)
        return panel

    def _build_cart(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.order_title = QLabel()
        self.order_title.setObjectName("PageTitle")
        layout.addWidget(self.order_title)
        self.items = QTableWidget(0, 4)
        self.items.setHorizontalHeaderLabels(["Produit", "Qté", "Prix U.", "Total"])
        self.items.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 54), (2, 85), (3, 90)):
            self.items.setColumnWidth(column, width)
        self.items.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.items.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.items, 1)
        remove = QPushButton("Retirer l'article sélectionné")
        remove.setObjectName("Danger")
        remove.clicked.connect(self._remove_selected)
        layout.addWidget(remove)
        self.total = QLabel()
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total.setStyleSheet("font-size: 26px; font-weight: 800;")
        layout.addWidget(self.total)
        close = QPushButton("Fermer la commande")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        return panel

    def _reload_categories(self) -> None:
        current = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Toutes les catégories", None)
        for category in CategoryController.list():
            self.category_filter.addItem(category.name, category.id)
        index = self.category_filter.findData(current)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _reload_products(self) -> None:
        self._clear_grid()
        currency = settings_service.get_currency()
        products = ProductController.list(
            search=self.search_input.text().strip(),
            category_id=self.category_filter.currentData(),
        )
        for index, product in enumerate(products):
            button = QPushButton(
                f"{product.name}\n{format_money(product.sale_price, currency)}"
            )
            button.setMinimumSize(150, 92)
            button.setStyleSheet(
                "QPushButton { border: 1px solid #cbd5e1; border-radius: 10px;"
                " background: #ffffff; font-weight: 600; }"
                "QPushButton:hover { border: 2px solid #2563eb; }"
            )
            button.setToolTip(
                f"Stock : {format_quantity(product.quantity)} {product.unit_name}".strip()
            )
            button.clicked.connect(
                lambda _=False, product_id=product.id: self._add_product(product_id)
            )
            self.grid.addWidget(button, index // 3, index % 3)
        self.grid.setRowStretch((len(products) + 2) // 3, 1)

    def _add_product(self, product_id: int) -> None:
        product = ProductController.get(product_id)
        if not product:
            warn(self, "Produit introuvable.")
            return
        try:
            order_service.OrderService.add_product(
                self.order_id,
                product_id=product.id,
                product_name=product.name,
                unit_price=float(product.sale_price),
            )
            self._reload_order()
        except ValueError as exc:
            warn(self, str(exc))

    def _reload_order(self) -> None:
        order = order_service.OrderService.get_open_for_table(self.table.id)
        if not order:
            self.reject()
            return
        currency = settings_service.get_currency()
        self.order_title.setText(f"{self.table.display_name} · {order.public_id}")
        self.items.setRowCount(len(order.items))
        for row, line in enumerate(order.items):
            name = QTableWidgetItem(line.product_name)
            name.setData(Qt.ItemDataRole.UserRole, line.id)
            self.items.setItem(row, 0, name)
            self.items.setItem(row, 1, QTableWidgetItem(format_quantity(line.quantity)))
            self.items.setItem(row, 2, QTableWidgetItem(format_money(line.unit_price, currency)))
            self.items.setItem(row, 3, QTableWidgetItem(format_money(line.line_total, currency)))
        self.total.setText(f"Total : {format_money(order.total, currency)}")

    def _remove_selected(self) -> None:
        row = self.items.currentRow()
        if row < 0:
            warn(self, "Sélectionnez un article.")
            return
        item_id = self.items.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if not confirm(self, "Retirer cet article de la commande ?", "Commande"):
            return
        try:
            order_service.OrderService.remove_item(self.order_id, item_id)
            self._reload_order()
        except ValueError as exc:
            warn(self, str(exc))
