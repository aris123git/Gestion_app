"""Module Caisse : interface de vente rapide."""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.controllers.client_controller import ClientController
from app.controllers.product_controller import ProductController
from app.controllers.sale_controller import (
    CartLine,
    InsufficientPaymentError,
    SaleController,
)
from app.services import audit_service, settings_service
from app.ui.dialogs.payment_dialog import PaymentDialog
from app.ui.dialogs.price_change_dialog import PriceChangeDialog
from app.ui.dialogs.ticket_dialog import TicketDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import info, page_title, warn
from app.utils.helpers import format_money, format_quantity, to_float


class POSPage(QWidget):
    """Écran de caisse : catalogue à gauche, panier à droite."""

    # Colonnes du panier
    COL_NAME, COL_QTY, COL_PRICE, COL_TOTAL, COL_DEL = range(5)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.cart: List[CartLine] = []
        self._updating = False
        self._client_map: Dict[int, int] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        root.addWidget(self._build_catalog(), 5)
        root.addWidget(self._build_cart(), 4)

    # --- Catalogue (gauche) -----------------------------------------------
    def _build_catalog(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(page_title("Caisse"))

        search_row = QHBoxLayout()
        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("Scanner / saisir un code-barres puis Entrée")
        self.barcode_input.returnPressed.connect(self._add_by_barcode)
        search_row.addWidget(self.barcode_input)
        layout.addLayout(search_row)

        filter_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Rechercher un produit…")
        self.search_input.textChanged.connect(self._reload_products)
        self.category_filter = QComboBox()
        self.category_filter.currentIndexChanged.connect(self._reload_products)
        filter_row.addWidget(self.search_input, 3)
        filter_row.addWidget(self.category_filter, 2)
        layout.addLayout(filter_row)

        self.product_table = QTableWidget(0, 3)
        self.product_table.setHorizontalHeaderLabels(["Produit", "Prix", "Stock"])
        self.product_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.product_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.product_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.product_table.doubleClicked.connect(self._add_selected_product)
        layout.addWidget(self.product_table)

        add_button = QPushButton("Ajouter au panier")
        add_button.setObjectName("Primary")
        add_button.clicked.connect(self._add_selected_product)
        layout.addWidget(add_button)

        return panel

    # --- Panier (droite) ---------------------------------------------------
    def _build_cart(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(page_title("Panier"))
        header.addStretch()
        clear = QPushButton("Vider")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear_cart)
        header.addWidget(clear)
        layout.addLayout(header)

        client_row = QHBoxLayout()
        client_row.addWidget(QLabel("Client :"))
        self.client_combo = QComboBox()
        client_row.addWidget(self.client_combo, 1)
        layout.addLayout(client_row)

        self.cart_table = QTableWidget(0, 5)
        self.cart_table.setHorizontalHeaderLabels(
            ["Produit", "Qté", "Prix U.", "Total", ""]
        )
        self.cart_table.horizontalHeader().setSectionResizeMode(
            self.COL_NAME, QHeaderView.ResizeMode.Stretch
        )
        self.cart_table.setColumnWidth(self.COL_QTY, 70)
        self.cart_table.setColumnWidth(self.COL_PRICE, 100)
        self.cart_table.setColumnWidth(self.COL_TOTAL, 110)
        self.cart_table.setColumnWidth(self.COL_DEL, 44)
        self.cart_table.itemChanged.connect(self._on_cart_edited)
        layout.addWidget(self.cart_table)

        # Remise + total
        discount_row = QHBoxLayout()
        discount_row.addWidget(QLabel("Remise :"))
        self.discount_input = QDoubleSpinBox()
        self.discount_input.setRange(0, 1_000_000_000)
        self.discount_input.setDecimals(0)
        self.discount_input.setSingleStep(100)
        self.discount_input.valueChanged.connect(self._update_total)
        discount_row.addWidget(self.discount_input)
        discount_row.addStretch()
        layout.addLayout(discount_row)

        self.total_label = QLabel("Total : 0")
        self.total_label.setStyleSheet("font-size: 26px; font-weight: 800;")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.total_label)

        pay_button = QPushButton("Encaisser (Payer)")
        pay_button.setObjectName("Success")
        pay_button.setMinimumHeight(52)
        pay_button.clicked.connect(self._checkout)
        layout.addWidget(pay_button)

        return panel

    # --- Chargement des données -------------------------------------------
    def refresh(self) -> None:
        self._reload_categories()
        self._reload_products()
        self._reload_clients()

    def _reload_categories(self) -> None:
        from app.controllers.category_controller import CategoryController

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

    def _reload_clients(self) -> None:
        self.client_combo.blockSignals(True)
        self.client_combo.clear()
        self.client_combo.addItem("Client de passage", None)
        for client in ClientController.list():
            self.client_combo.addItem(client.name, client.id)
        self.client_combo.blockSignals(False)

    def _reload_products(self) -> None:
        products = ProductController.list(
            search=self.search_input.text().strip(),
            category_id=self.category_filter.currentData(),
        )
        currency = settings_service.get_currency()
        self.product_table.setRowCount(len(products))
        for row, product in enumerate(products):
            name_item = QTableWidgetItem(product.name)
            name_item.setData(Qt.ItemDataRole.UserRole, product.id)
            self.product_table.setItem(row, 0, name_item)
            self.product_table.setItem(
                row, 1, QTableWidgetItem(format_money(product.sale_price, currency))
            )
            stock_item = QTableWidgetItem(
                f"{format_quantity(product.quantity)} {product.unit_name}".strip()
            )
            if product.is_out_of_stock:
                stock_item.setForeground(Qt.GlobalColor.red)
            self.product_table.setItem(row, 2, stock_item)

    # --- Ajout au panier ---------------------------------------------------
    def _add_by_barcode(self) -> None:
        code = self.barcode_input.text().strip()
        if not code:
            return
        product = ProductController.find_by_barcode(code)
        self.barcode_input.clear()
        if not product:
            warn(self, f"Aucun produit avec le code-barres « {code} ».")
            return
        self._add_product(product)

    def _add_selected_product(self) -> None:
        row = self.product_table.currentRow()
        if row < 0:
            return
        product_id = self.product_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        product = ProductController.get(product_id)
        if product:
            self._add_product(product)

    def _add_product(self, product) -> None:
        for line in self.cart:
            if line.product_id == product.id:
                line.quantity += 1
                self._render_cart()
                return
        self.cart.append(
            CartLine(
                product_id=product.id,
                name=product.name,
                unit_price=float(product.sale_price),
                quantity=1,
                purchase_price=float(product.purchase_price),
            )
        )
        self._render_cart()

    # --- Rendu et édition du panier ---------------------------------------
    def _render_cart(self) -> None:
        self._updating = True
        currency = settings_service.get_currency()
        self.cart_table.setRowCount(len(self.cart))
        for row, line in enumerate(self.cart):
            name_item = QTableWidgetItem(line.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            qty_item = QTableWidgetItem(format_quantity(line.quantity))
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            price_item = QTableWidgetItem(f"{float(line.unit_price):g}")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            total_item = QTableWidgetItem(format_money(line.total, currency))
            total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self.cart_table.setItem(row, self.COL_NAME, name_item)
            self.cart_table.setItem(row, self.COL_QTY, qty_item)
            self.cart_table.setItem(row, self.COL_PRICE, price_item)
            self.cart_table.setItem(row, self.COL_TOTAL, total_item)

            delete_button = QPushButton("✕")
            delete_button.setObjectName("Danger")
            delete_button.clicked.connect(lambda _=False, r=row: self._remove_line(r))
            self.cart_table.setCellWidget(row, self.COL_DEL, delete_button)

        self._updating = False
        self._update_total()

    def _remove_line(self, row: int) -> None:
        if 0 <= row < len(self.cart):
            self.cart.pop(row)
            self._render_cart()

    def _on_cart_edited(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        row = item.row()
        if row >= len(self.cart):
            return
        line = self.cart[row]

        if item.column() == self.COL_QTY:
            qty = to_float(item.text())
            if qty <= 0:
                self._remove_line(row)
                return
            line.quantity = qty
            self._render_cart()

        elif item.column() == self.COL_PRICE:
            new_price = to_float(item.text())
            if new_price <= 0:
                self._render_cart()
                return
            if new_price != float(line.unit_price):
                dialog = PriceChangeDialog(line.name, self)
                if dialog.exec():
                    line.unit_price = new_price
                    if dialog.choice == "permanent" and line.product_id:
                        ProductController.update_price(line.product_id, new_price)
                        audit_service.log_action(
                            "Modification prix",
                            "Product",
                            f"{line.name} -> {new_price}",
                            self.state.user_id,
                            getattr(self.state.current_user, "username", ""),
                        )
                self._render_cart()

    def _cart_total(self) -> float:
        subtotal = sum(line.total for line in self.cart)
        return max(0.0, subtotal - self.discount_input.value())

    def _update_total(self) -> None:
        currency = settings_service.get_currency()
        self.total_label.setText(f"Total : {format_money(self._cart_total(), currency)}")

    def _clear_cart(self) -> None:
        self.cart.clear()
        self.discount_input.setValue(0)
        self._render_cart()

    # --- Encaissement ------------------------------------------------------
    def _checkout(self) -> None:
        if not self.cart:
            warn(self, "Le panier est vide.")
            return
        total = self._cart_total()
        client_id: Optional[int] = self.client_combo.currentData()
        dialog = PaymentDialog(total, allow_credit=client_id is not None, parent=self)
        if not dialog.exec():
            return
        try:
            result = SaleController.create_sale(
                lines=list(self.cart),
                payments=dialog.result_payments,
                amount_received=dialog.amount_received,
                discount=self.discount_input.value(),
                client_id=client_id,
                user_id=self.state.user_id,
                allow_credit=dialog.use_credit,
            )
        except InsufficientPaymentError as exc:
            warn(self, str(exc), "Paiement insuffisant")
            return
        except ValueError as exc:
            warn(self, str(exc))
            return

        audit_service.log_action(
            "Vente",
            "Sale",
            f"{result.ticket_number} total={result.total}",
            self.state.user_id,
            getattr(self.state.current_user, "username", ""),
        )
        currency = settings_service.get_currency()
        info(
            self,
            f"Vente enregistrée : {result.ticket_number}\n"
            f"Total : {format_money(result.total, currency)}\n"
            f"Monnaie rendue : {format_money(result.change_due, currency)}",
            "Vente réussie",
        )

        sale = SaleController.get(result.sale_id)
        if sale:
            TicketDialog(sale, self).exec()

        self._clear_cart()
        self._reload_products()
        self.state.notify_data_changed()
