"""Page de gestion des produits (liste, ajout, modification, suppression)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.controllers.category_controller import CategoryController
from app.controllers.product_controller import ProductController
from app.reports.excel_report import export_products_excel
from app.services import audit_service, settings_service
from app.ui.dialogs.product_dialog import ProductDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, page_title, warn
from app.utils.helpers import format_money, format_quantity


class ProductsPage(QWidget):
    HEADERS = ["Nom", "Catégorie", "Code-barres", "Prix vente", "Stock", "Unité"]

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.addWidget(page_title("Produits"))
        header.addStretch()
        export_button = QPushButton("Exporter Excel")
        export_button.clicked.connect(self._export)
        add_button = QPushButton("+ Nouveau produit")
        add_button.setObjectName("Primary")
        add_button.clicked.connect(self._add)
        header.addWidget(export_button)
        header.addWidget(add_button)
        layout.addLayout(header)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (nom, code-barres, référence)…")
        self.search.textChanged.connect(self.refresh)
        self.category_filter = QComboBox()
        self.category_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.search, 3)
        filters.addWidget(self.category_filter, 1)
        layout.addLayout(filters)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._edit)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        actions.addStretch()
        edit_button = QPushButton("Modifier")
        edit_button.clicked.connect(self._edit)
        delete_button = QPushButton("Supprimer")
        delete_button.setObjectName("Danger")
        delete_button.clicked.connect(self._delete)
        actions.addWidget(edit_button)
        actions.addWidget(delete_button)
        layout.addLayout(actions)

    def refresh(self) -> None:
        self._reload_categories()
        products = ProductController.list(
            search=self.search.text().strip(),
            category_id=self.category_filter.currentData(),
        )
        currency = settings_service.get_currency()
        self._ids = [p.id for p in products]
        self.table.setRowCount(len(products))
        for row, product in enumerate(products):
            self.table.setItem(row, 0, QTableWidgetItem(product.name))
            self.table.setItem(row, 1, QTableWidgetItem(product.category_name))
            self.table.setItem(row, 2, QTableWidgetItem(product.barcode))
            self.table.setItem(
                row, 3, QTableWidgetItem(format_money(product.sale_price, currency))
            )
            stock_item = QTableWidgetItem(format_quantity(product.quantity))
            if product.is_out_of_stock:
                stock_item.setForeground(Qt.GlobalColor.red)
            elif product.is_low_stock:
                stock_item.setForeground(Qt.GlobalColor.darkYellow)
            self.table.setItem(row, 4, stock_item)
            self.table.setItem(row, 5, QTableWidgetItem(product.unit_name))

    def _reload_categories(self) -> None:
        current = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Toutes", None)
        for category in CategoryController.list():
            self.category_filter.addItem(category.name, category.id)
        index = self.category_filter.findData(current)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _add(self) -> None:
        dialog = ProductDialog(parent=self)
        if dialog.exec() and dialog.data:
            product = ProductController.create(dialog.data)
            audit_service.log_action(
                "Création produit", "Product", product.name,
                self.state.user_id, getattr(self.state.current_user, "username", ""),
            )
            self.refresh()
            self.state.notify_data_changed()

    def _edit(self) -> None:
        product_id = self._selected_id()
        if not product_id:
            warn(self, "Veuillez sélectionner un produit.")
            return
        product = ProductController.get(product_id)
        dialog = ProductDialog(product=product, parent=self)
        if dialog.exec() and dialog.data:
            ProductController.update(product_id, dialog.data)
            audit_service.log_action(
                "Modification produit", "Product", dialog.data["name"],
                self.state.user_id, getattr(self.state.current_user, "username", ""),
            )
            self.refresh()
            self.state.notify_data_changed()

    def _delete(self) -> None:
        product_id = self._selected_id()
        if not product_id:
            warn(self, "Veuillez sélectionner un produit.")
            return
        if not self.state.is_admin:
            warn(self, "Seul un administrateur peut supprimer un produit.")
            return
        if confirm(self, "Supprimer définitivement ce produit ?"):
            ProductController.delete(product_id)
            audit_service.log_action(
                "Suppression produit", "Product", str(product_id),
                self.state.user_id, getattr(self.state.current_user, "username", ""),
            )
            self.refresh()
            self.state.notify_data_changed()

    def _export(self) -> None:
        products = ProductController.list(only_active=False)
        path = export_products_excel(products)
        info(self, f"Export réalisé :\n{path}")
