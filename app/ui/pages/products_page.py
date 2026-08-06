"""Page de gestion des produits (liste, ajout, modification, suppression)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from app.controllers.category_controller import CategoryController
from app.controllers.product_controller import ProductController
from app.reports.excel_report import export_products_excel
from app.services import audit_service, permissions as perms, settings_service
from app.ui.dialogs.product_dialog import ProductDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, page_title, warn
from app.utils.helpers import format_money, format_quantity


class ProductsPage(QWidget):
    HEADERS = ["Nom", "Catégorie", "Code-barres", "Prix vente", "Stock", "Unité"]
    LIST_LIMIT = 5000

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
        self.export_button = QPushButton("Exporter Excel")
        self.export_button.clicked.connect(self._export)
        self.add_button = QPushButton("+ Nouveau produit")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self._add)
        header.addWidget(self.export_button)
        header.addWidget(self.add_button)
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

        self.limit_note = QLabel("")
        self.limit_note.setStyleSheet("color: #b45309; font-size: 12px;")
        self.limit_note.setWordWrap(True)
        layout.addWidget(self.limit_note)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        # nom s'étire
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # colonnes restantes : interactive pour laisser la possibilité de scroll
        for col in range(1, len(self.HEADERS)):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._edit)
        # permettre scroll horizontal fin
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        # permettre au tableau d'occuper l'espace disponible
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        actions.addStretch()
        self.edit_button = QPushButton("Modifier")
        self.edit_button.clicked.connect(self._edit)
        self.delete_button = QPushButton("Supprimer")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        layout.addLayout(actions)
        self._apply_permissions()

    def _apply_permissions(self) -> None:
        can_manage = self.state.can(perms.MANAGE_PRODUCTS)
        can_delete = self.state.can(perms.DELETE_PRODUCTS)
        self.add_button.setVisible(can_manage)
        self.edit_button.setVisible(can_manage)
        self.delete_button.setVisible(can_delete)
        self.export_button.setVisible(self.state.can(perms.VIEW_PROFITS) or can_manage)

    def refresh(self) -> None:
        self._apply_permissions()
        self._reload_categories()
        products = ProductController.list(
            search=self.search.text().strip(),
            category_id=self.category_filter.currentData(),
            limit=self.LIST_LIMIT,
        )
        self.limit_note.setText(
            f"Affichage limité aux {self.LIST_LIMIT} premiers produits. "
            "Affinez la recherche ou la catégorie si le produit recherché n'apparaît pas."
            if len(products) == self.LIST_LIMIT
            else ""
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

    def select_product(self, product_id: int) -> None:
        if product_id not in self._ids:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.category_filter.setCurrentIndex(0)
            self.refresh()
        if product_id in self._ids:
            row = self._ids.index(product_id)
            self.table.selectRow(row)
            item = self.table.item(row, 0)
            if item:
                self.table.scrollToItem(item)

    def _add(self) -> None:
        if not self.state.can(perms.MANAGE_PRODUCTS):
            warn(self, "Vous n'avez pas l'autorisation d'ajouter un produit.")
            return
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
        if not self.state.can(perms.MANAGE_PRODUCTS):
            return
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
        if not self.state.can(perms.DELETE_PRODUCTS):
            warn(self, "Vous n'avez pas l'autorisation de supprimer un produit.")
            return
        if confirm(
            self,
            "Supprimer ce produit ?\n\n"
            "S'il existe dans des ventes, il sera simplement désactivé pour "
            "conserver l'historique.",
        ):
            result = ProductController.delete(product_id)
            audit_service.log_action(
                "Suppression produit", "Product", str(product_id),
                self.state.user_id, getattr(self.state.current_user, "username", ""),
            )
            self.refresh()
            self.state.notify_data_changed()
            if result == "deactivated":
                info(self, "Produit désactivé : il n'apparaît plus en caisse.")

    def _export(self) -> None:
        products = ProductController.list(only_active=False, limit=100_000)
        path = export_products_excel(products)
        info(self, f"Export réalisé :\n{path}")
