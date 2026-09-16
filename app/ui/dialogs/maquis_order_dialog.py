"""Écran de commande d'une table — Maquis Caisse PC, style tablette.

Reprend point pour point l'affichage de la caisse : mêmes vignettes produits,
mêmes puces de catégories, même stepper − quantité + dans le panier.
L'encaissement (« Marquer payée ») enregistre une vraie vente (stock déduit,
tableau de bord, rapports) mais n'imprime rien.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.controllers.category_controller import CategoryController
from app.controllers.product_controller import ProductController
from app.i18n import t
from app.services import order_service, settings_service
from app.ui.dialogs.free_amount_dialog import FreeAmountDialog
from app.ui.widgets.helpers import confirm, info, page_title, warn
from app.ui.widgets.touch_pos import (
    make_category_chip,
    make_product_card,
    make_qty_stepper,
)
from app.utils.helpers import format_money, format_quantity


class MaquisOrderDialog(QDialog):
    """Catalogue tactile à gauche, commande de la table à droite."""

    COL_NAME, COL_QTY, COL_PRICE, COL_TOTAL, COL_DEL = range(5)

    def __init__(self, table, order, state=None, parent=None):
        super().__init__(parent)
        self.table = table
        self.order_id = order.id
        self.state = state
        self._item_ids: list[int] = []
        self._items: list = []
        self._category_id = None
        self.settled_ticket: str | None = None
        self.setWindowTitle(f"{t('Commande')} — {table.display_name}")
        self.setMinimumSize(860, 560)
        self.resize(1200, 720)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._build_catalog(), 5)
        root.addWidget(self._build_order_panel(), 4)
        self._reload_categories()
        self._reload_products()
        self._reload_order()

    # ------------------------------------------------------------------ UI --
    def _build_catalog(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName('Card')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(page_title(t('pos.title')))
        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText(t('pos.barcode'))
        self.barcode_input.returnPressed.connect(self._add_by_barcode)
        layout.addWidget(self.barcode_input)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t('pos.search_product'))
        self.search_input.textChanged.connect(self._reload_products)
        layout.addWidget(self.search_input)
        self.category_chips_scroll = QScrollArea()
        self.category_chips_scroll.setWidgetResizable(True)
        self.category_chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.category_chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.category_chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.category_chips_scroll.setFixedHeight(56)
        self.category_chips_host = QWidget()
        self.category_chips_layout = QHBoxLayout(self.category_chips_host)
        self.category_chips_layout.setContentsMargins(0, 0, 0, 0)
        self.category_chips_layout.setSpacing(8)
        self.category_chips_scroll.setWidget(self.category_chips_host)
        layout.addWidget(self.category_chips_scroll)
        self.product_grid_scroll = QScrollArea()
        self.product_grid_scroll.setWidgetResizable(True)
        self.product_grid_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.product_grid_host = QWidget()
        self.product_grid_layout = QGridLayout(self.product_grid_host)
        self.product_grid_layout.setContentsMargins(4, 4, 4, 4)
        self.product_grid_layout.setSpacing(10)
        self.product_grid_scroll.setWidget(self.product_grid_host)
        layout.addWidget(self.product_grid_scroll, 1)
        return panel

    def _build_order_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName('Card')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.order_title = page_title('')
        layout.addWidget(self.order_title)
        self.items_table = QTableWidget(0, 5)
        self.items_table.setHorizontalHeaderLabels([t('Produit'), t('Qté'), t('Prix U.'), t('Total'), ''])
        self.items_table.horizontalHeader().setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.items_table.setColumnWidth(self.COL_QTY, 96)
        self.items_table.setColumnWidth(self.COL_PRICE, 100)
        self.items_table.setColumnWidth(self.COL_TOTAL, 110)
        self.items_table.setColumnWidth(self.COL_DEL, 44)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.items_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.items_table.verticalHeader().setVisible(False)
        layout.addWidget(self.items_table, 1)
        self.total_label = QLabel(t('Total : 0'))
        self.total_label.setStyleSheet('font-size: 26px; font-weight: 800;')
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.total_label)
        pay = QPushButton(t('Marquer payée — sans impression'))
        pay.setObjectName('Success')
        pay.setMinimumHeight(52)
        pay.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        pay.clicked.connect(self._settle)
        layout.addWidget(pay)
        actions = QHBoxLayout()
        cancel = QPushButton(t('Annuler la commande'))
        cancel.setObjectName('Danger')
        cancel.clicked.connect(self._cancel_order)
        close = QPushButton(t('Fermer (commande reste ouverte)'))
        close.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(close, 1)
        layout.addLayout(actions)
        return panel

    # ------------------------------------------------------------ catalogue --
    def _reload_categories(self) -> None:
        while self.category_chips_layout.count():
            item = self.category_chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        categories = CategoryController.list()

        def add_chip(label: str, cat_id, tooltip: str = ''):
            btn = make_category_chip(label, cat_id == self._category_id, lambda cid=cat_id: self._select_category(cid), tooltip)
            self.category_chips_layout.addWidget(btn)
        add_chip(t('pos.all_categories'), None)
        for category in categories:
            add_chip(category.name, category.id, (category.description or '').strip())
        self.category_chips_layout.addStretch(1)

    def _select_category(self, category_id) -> None:
        self._category_id = category_id
        self._reload_categories()
        self._reload_products()

    def _clear_grid(self) -> None:
        while self.product_grid_layout.count():
            item = self.product_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _reload_products(self) -> None:
        self._clear_grid()
        currency = settings_service.get_currency()
        products = ProductController.list(search=self.search_input.text().strip(), category_id=self._category_id)
        cols = 3
        for index, product in enumerate(products):
            card = make_product_card(product, currency, self._add_product_id)
            self.product_grid_layout.addWidget(card, index // cols, index % cols)
        self.product_grid_layout.setRowStretch((len(products) + cols - 1) // cols, 1)

    def _add_by_barcode(self) -> None:
        code = self.barcode_input.text().strip()
        if not code:
            return
        product = ProductController.find_by_barcode(code)
        self.barcode_input.clear()
        if not product:
            warn(self, f'Aucun produit avec le code-barres « {code} ».')
            return
        self._add_product_id(product.id)

    def _add_product_id(self, product_id: int) -> None:
        product = ProductController.get(product_id)
        if not product:
            warn(self, t('Produit introuvable.'))
            return
        if getattr(product, 'free_amount_sale', False):
            self._add_free_amount(product)
            return
        try:
            order_service.OrderService.add_product(self.order_id, product.id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._reload_order()

    def _add_free_amount(self, product) -> None:
        sale_price = float(product.sale_price or 0)
        if sale_price <= 0:
            warn(self, f'« {product.name} » : définissez un prix de vente de référence pour le montant libre.')
            return
        dialog = FreeAmountDialog(product.name, sale_price, parent=self)
        if not dialog.exec() or not dialog.amount:
            return
        amount = float(dialog.amount)
        currency = settings_service.get_currency()
        try:
            order_service.OrderService.add_item(
                self.order_id,
                product_id=product.id,
                product_name=f'{product.name} — {format_money(amount, currency)}',
                quantity=amount / sale_price,
                unit_price=sale_price,
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._reload_order()

    # ------------------------------------------------------------- commande --
    def _reload_order(self) -> None:
        order = order_service.OrderService.get(self.order_id)
        if not order or order.status != 'ouverte':
            self.accept()
            return
        currency = settings_service.get_currency()
        self.order_title.setText(f'{self.table.display_name} · {order.public_id}')
        self._items = list(order.items)
        self._item_ids = [item.id for item in self._items]
        self.items_table.setRowCount(len(self._items))
        for row, line in enumerate(self._items):
            free_amount = self._is_free_amount(line)
            name_item = QTableWidgetItem(line.product_name)
            qty_item = QTableWidgetItem(format_quantity(line.quantity))
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price_item = QTableWidgetItem(f'{float(line.unit_price):g}')
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            total_item = QTableWidgetItem(format_money(float(line.line_total or 0), currency))
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.items_table.setItem(row, self.COL_NAME, name_item)
            self.items_table.setItem(row, self.COL_QTY, qty_item)
            self.items_table.setItem(row, self.COL_PRICE, price_item)
            self.items_table.setItem(row, self.COL_TOTAL, total_item)
            if not free_amount:
                stepper = make_qty_stepper(format_quantity(line.quantity), lambda r=row: self._step_qty(r, -1), lambda r=row: self._step_qty(r, 1))
                self.items_table.setCellWidget(row, self.COL_QTY, stepper)
            delete_button = QPushButton(t('✕'))
            delete_button.setObjectName('Danger')
            delete_button.clicked.connect(lambda _=False, r=row: self._remove_row(r))
            self.items_table.setCellWidget(row, self.COL_DEL, delete_button)
        self.total_label.setText(f'Total : {format_money(float(order.total or 0), currency)}')

    @staticmethod
    def _is_free_amount(line) -> bool:
        if not line.product_id:
            return False
        product = ProductController.get(line.product_id)
        return bool(getattr(product, 'free_amount_sale', False)) if product else False

    def _step_qty(self, row: int, delta: float) -> None:
        if not 0 <= row < len(self._items):
            return
        line = self._items[row]
        try:
            order_service.OrderService.set_item_quantity(self.order_id, line.id, float(line.quantity) + delta)
        except ValueError as exc:
            warn(self, str(exc))
        self._reload_order()

    def _remove_row(self, row: int) -> None:
        if not 0 <= row < len(self._item_ids):
            return
        try:
            order_service.OrderService.remove_item(self.order_id, self._item_ids[row])
        except ValueError as exc:
            warn(self, str(exc))
        self._reload_order()

    def _settle(self) -> None:
        if not confirm(self, t('Marquer cette commande comme payée ?\n\nLa vente sera enregistrée (stock, rapports) sans impression.'), t('Commande')):
            return
        user = getattr(self.state, 'current_user', None) if self.state else None
        try:
            result = order_service.OrderService.settle(self.order_id, user_id=getattr(user, 'id', None))
        except Exception as exc:
            warn(self, str(exc))
            return
        self.settled_ticket = result.ticket_number
        currency = settings_service.get_currency()
        if self.state is not None:
            self.state.notify_data_changed()
        info(self, f'Commande payée — vente {result.ticket_number} enregistrée '
                   f'({format_money(result.total, currency)}). Aucune impression.\n'
                   f"Table libérée s'il ne reste pas d'autre commande.")
        self.accept()

    def _cancel_order(self) -> None:
        if not confirm(self, t('Annuler cette commande ?'), t('Commande')):
            return
        try:
            order_service.OrderService.cancel(self.order_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        if self.state is not None:
            self.state.notify_data_changed()
        self.accept()
