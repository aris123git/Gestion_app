"""Module Caisse : interface de vente rapide."""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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

from app import config
from app.controllers.client_controller import ClientController
from app.controllers.product_controller import ProductController
from app.controllers.sale_controller import (
    CartLine,
    BelowMinPriceError,
    InsufficientPaymentError,
    InsufficientStockError,
    SaleController,
)
from app.services import audit_service, permissions as perms, settings_service
from app.ui.dialogs.free_amount_dialog import FreeAmountDialog
from app.ui.dialogs.payment_dialog import PaymentDialog
from app.ui.dialogs.price_change_dialog import PriceChangeDialog
from app.ui.dialogs.ticket_dialog import TicketDialog
from app.ui.responsive import LayoutProfile
from app.ui.state import AppState
from app.ui.widgets.client_search import ClientSearchField
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
        self._pending_sale_id: Optional[int] = None

        self._root = QHBoxLayout(self)
        self._root.setContentsMargins(12, 12, 12, 12)
        self._root.setSpacing(12)

        self._catalog = self._build_catalog()
        self._cart_panel = self._build_cart()
        # Scroll si l'écran est trop bas (empilement catalogue + panier).
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_host = QWidget()
        self._scroll_layout = QHBoxLayout(self._scroll_host)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(12)
        self._scroll_layout.addWidget(self._catalog, 5)
        self._scroll_layout.addWidget(self._cart_panel, 4)
        self._scroll.setWidget(self._scroll_host)
        self._root.addWidget(self._scroll, 1)

        self._pay_button: Optional[QPushButton] = None
        self.state.layout_changed.connect(self._on_layout_changed)
        if self.state.layout is not None:
            self._on_layout_changed(self.state.layout)

    def _on_layout_changed(self, profile: LayoutProfile) -> None:
        margins = 6 if profile.density == "compact" else (10 if profile.is_narrow else 12)
        self._root.setContentsMargins(margins, margins, margins, margins)
        spacing = 8 if profile.is_short or profile.is_narrow else 12
        self._root.setSpacing(spacing)
        self._scroll_layout.setSpacing(spacing)

        stack = profile.stack_panels
        direction = (
            QHBoxLayout.Direction.TopToBottom
            if stack
            else QHBoxLayout.Direction.LeftToRight
        )
        self._scroll_layout.setDirection(direction)
        if stack:
            self._scroll_layout.setStretch(0, 3)
            self._scroll_layout.setStretch(1, 2)
            # Hauteurs min plus basses sur écrans courts pour éviter le clipping.
            cat_min = 160 if profile.is_short else 220
            cart_min = 220 if profile.is_short else 280
            self._catalog.setMinimumHeight(cat_min)
            self._cart_panel.setMinimumHeight(cart_min)
            self._catalog.setMinimumWidth(0)
            self._cart_panel.setMinimumWidth(0)
        else:
            self._scroll_layout.setStretch(0, 5)
            self._scroll_layout.setStretch(1, 4)
            self._catalog.setMinimumHeight(0)
            self._cart_panel.setMinimumHeight(0)
            # Répartir l'espace : catalogue un peu plus large que panier.
            self._catalog.setMinimumWidth(280)
            self._cart_panel.setMinimumWidth(260)

        # Colonnes panier : plus étroites sur petit écran.
        if profile.content_width < 700 or stack:
            self.cart_table.setColumnWidth(self.COL_QTY, 52)
            self.cart_table.setColumnWidth(self.COL_PRICE, 72)
            self.cart_table.setColumnWidth(self.COL_TOTAL, 80)
            self.cart_table.setColumnWidth(self.COL_DEL, 36)
        elif profile.content_width < 1100:
            self.cart_table.setColumnWidth(self.COL_QTY, 60)
            self.cart_table.setColumnWidth(self.COL_PRICE, 84)
            self.cart_table.setColumnWidth(self.COL_TOTAL, 92)
            self.cart_table.setColumnWidth(self.COL_DEL, 40)
        else:
            self.cart_table.setColumnWidth(self.COL_QTY, 70)
            self.cart_table.setColumnWidth(self.COL_PRICE, 100)
            self.cart_table.setColumnWidth(self.COL_TOTAL, 110)
            self.cart_table.setColumnWidth(self.COL_DEL, 44)

        total_px = 20 if profile.density == "compact" else (22 if profile.is_narrow else 26)
        self.total_label.setStyleSheet(
            f"font-size: {total_px}px; font-weight: 800;"
        )
        if self._pay_button is not None:
            self._pay_button.setMinimumHeight(44 if profile.density != "comfortable" else 52)
            self._pay_button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )

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
        self.client_search = ClientSearchField(
            placeholder="Tapez un nom ou un téléphone…",
        )
        self.client_search.client_selected.connect(self._on_client_selected)
        client_row.addWidget(self.client_search, 1)
        layout.addLayout(client_row)
        hint = QLabel(
            "Suggestions au fur et à mesure. Sélectionnez le client pour facturer "
            "ou mettre en dette."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(hint)

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
        if not self.state.can(perms.APPLY_DISCOUNT):
            self.discount_input.setEnabled(False)
            self.discount_input.setToolTip(
                "Vous n'avez pas l'autorisation d'appliquer une remise."
            )
        elif getattr(self.state.current_user, "role", "") == perms.ROLE_CASHIER:
            from app.services.cash_controls import get_max_discount_percent

            pct = get_max_discount_percent()
            self.discount_input.setToolTip(
                f"Plafond caissier : {pct:g} % du sous-total"
            )
        discount_row.addWidget(self.discount_input)
        discount_row.addStretch()
        layout.addLayout(discount_row)

        self.total_label = QLabel("Total : 0")
        self.total_label.setStyleSheet("font-size: 26px; font-weight: 800;")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.total_label)

        pending_row = QHBoxLayout()
        hold_btn = QPushButton("Mettre en attente")
        hold_btn.clicked.connect(self._hold_sale)
        resume_btn = QPushButton("Reprendre…")
        resume_btn.clicked.connect(self._resume_pending)
        pending_row.addWidget(hold_btn)
        pending_row.addWidget(resume_btn)
        layout.addLayout(pending_row)

        pay_button = QPushButton("Encaisser (Payer)")
        pay_button.setObjectName("Success")
        pay_button.setMinimumHeight(52)
        pay_button.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        pay_button.clicked.connect(self._checkout)
        layout.addWidget(pay_button)
        self._pay_button = pay_button

        return panel

    # --- Chargement des données -------------------------------------------
    def refresh(self) -> None:
        self._reload_categories()
        self._reload_products()
        self._reload_clients()
        self._apply_large_text()

    def _apply_large_text(self) -> None:
        """Agrandit noms/prix catalogue + panier si activé dans Paramètres."""
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
        for table in (self.product_table, self.cart_table):
            table.setFont(font)
            table.verticalHeader().setDefaultSectionSize(row_h)
            table.verticalHeader().setVisible(False)
        # Prix catalogue un peu plus gros encore.
        for row in range(self.product_table.rowCount()):
            item = self.product_table.item(row, 1)
            if item is not None:
                item.setFont(price_font)
        for row in range(self.cart_table.rowCount()):
            for col in (self.COL_NAME, self.COL_PRICE, self.COL_TOTAL, self.COL_QTY):
                item = self.cart_table.item(row, col)
                if item is not None:
                    item.setFont(price_font if col != self.COL_NAME else font)

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

    def _reload_clients(self, select_id: Optional[int] = None) -> None:
        if select_id is not None:
            self.client_search.set_client(select_id)

    def _on_client_selected(self, client_id) -> None:
        # Réservé pour extensions (affichage solde dette, etc.).
        _ = client_id

    def _current_client_id(self) -> Optional[int]:
        return self.client_search.client_id

    def _cashier_max_credit(self) -> Optional[float]:
        from app.services.cash_controls import limits_for_user

        _, max_credit = limits_for_user(self.state.current_user)
        return max_credit

    def _current_client_phone(self) -> str:
        client_id = self._current_client_id()
        if client_id:
            client = ClientController.get(client_id)
            if client:
                return (client.phone or client.phone2 or "").strip()
        # Texte brut saisi (peut être un téléphone pour création).
        text = self.client_search.text()
        if text and any(ch.isdigit() for ch in text):
            # Garde les chiffres / + pour le dialogue de paiement.
            return "".join(ch for ch in text if ch.isdigit() or ch == "+")
        return ""

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
        self._apply_large_text()

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

    def _available_stock(self, product_id: int, exclude_cart: bool = False) -> float:
        """Stock restant (unités d'achat), en tenant compte du panier courant."""
        product = ProductController.get(product_id)
        if not product:
            return 0.0
        available = float(product.quantity)
        if not exclude_cart:
            for line in self.cart:
                if line.product_id == product_id:
                    available -= float(line.stock_quantity)
        return available

    def _min_price_for_product(self, product_id: Optional[int]) -> float:
        if not product_id:
            return 0.0
        product = ProductController.get(product_id)
        return float(product.min_price) if product else 0.0

    def _add_product(self, product) -> None:
        if getattr(product, "free_amount_sale", False):
            self._add_free_amount_product(product)
            return

        min_price = float(product.min_price or 0)
        sale_price = float(product.sale_price)
        if min_price > 0 and sale_price < min_price:
            warn(
                self,
                f"Impossible d'ajouter « {product.name} » : le prix de vente "
                f"{format_money(sale_price, settings_service.get_currency())} est inférieur "
                f"au prix minimum {format_money(min_price, settings_service.get_currency())}.",
                "Prix minimum",
            )
            return
        available = self._available_stock(product.id)
        requested = 1.0
        if available + 0.0001 < requested:
            warn(
                self,
                f"Stock insuffisant pour « {product.name} » : "
                f"disponible {format_quantity(available)}, demandé {format_quantity(requested)}.",
                "Stock insuffisant",
            )
            return
        for line in self.cart:
            if line.product_id == product.id and not line.free_amount:
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

    def _add_free_amount_product(self, product) -> None:
        """Ajoute une ligne au montant demandé (ex. 300 F de chinchard)."""
        sale_price = float(product.sale_price or 0)
        if sale_price <= 0:
            warn(
                self,
                f"« {product.name} » : définissez un prix de vente de référence "
                "(ex. F/kg) pour estimer la marge.",
            )
            return
        available = self._available_stock(product.id)
        if available + 0.0001 <= 0:
            warn(
                self,
                f"Stock insuffisant pour « {product.name} » : "
                f"disponible {format_quantity(available)}.",
                "Stock insuffisant",
            )
            return

        dialog = FreeAmountDialog(product.name, sale_price, parent=self)
        if not dialog.exec() or not dialog.amount:
            return

        amount = float(dialog.amount)
        from app.services import cash_controls

        if (
            getattr(self.state.current_user, "role", "") == perms.ROLE_CASHIER
            and amount > cash_controls.get_max_free_amount() + 0.009
        ):
            warn(
                self,
                f"Montant libre trop élevé pour un caissier "
                f"(max {cash_controls.get_max_free_amount():g} "
                f"{settings_service.get_currency()}).",
            )
            return

        estimated_qty = amount / sale_price
        pack = float(getattr(product, "pack_content", 0) or 0)
        cost_per_unit = float(product.cost_per_sale_unit)
        stock_needed = (
            round(estimated_qty / pack, 6) if pack > 0 else estimated_qty
        )
        if stock_needed > available + 0.0001:
            warn(
                self,
                f"Stock insuffisant pour « {product.name} » : "
                f"disponible {format_quantity(available)} "
                f"{product.unit_name or 'unité'}(s), "
                f"besoin estimé {format_quantity(stock_needed)}.",
                "Stock insuffisant",
            )
            return

        currency = settings_service.get_currency()
        display_name = f"{product.name} — {format_money(amount, currency)}"
        self.cart.append(
            CartLine(
                product_id=product.id,
                name=display_name,
                unit_price=sale_price,
                quantity=estimated_qty,
                purchase_price=cost_per_unit,
                free_amount=True,
                amount=amount,
                pack_content=pack,
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

            if line.free_amount:
                qty_item = QTableWidgetItem(f"≈ {format_quantity(line.quantity)}")
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                qty_item.setFlags(qty_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                qty_item.setToolTip(
                    "Quantité estimée (montant ÷ prix de référence). Non modifiable."
                )

                price_item = QTableWidgetItem(f"{float(line.unit_price):g}/kg")
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                price_item.setFlags(price_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                price_item.setToolTip("Prix de référence pour la marge estimée.")
            else:
                qty_item = QTableWidgetItem(format_quantity(line.quantity))
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                price_item = QTableWidgetItem(f"{float(line.unit_price):g}")
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not self.state.can(perms.MANAGE_PRICES):
                    price_item.setFlags(
                        price_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                    )

            total_item = QTableWidgetItem(format_money(line.total, currency))
            total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            total_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

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
        self._apply_large_text()

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

        if line.free_amount:
            # Montant libre : quantité et prix de référence ne sont pas éditables.
            self._render_cart()
            return

        if item.column() == self.COL_QTY:
            qty = to_float(item.text())
            if qty <= 0:
                self._remove_line(row)
                return
            if line.product_id:
                stock = self._available_stock(line.product_id, exclude_cart=True)
                if stock <= 0:
                    warn(
                        self,
                        f"Stock insuffisant : « {line.name} » est en rupture de stock.",
                        "Stock insuffisant",
                    )
                    self._render_cart()
                    return
                if qty > stock:
                    warn(
                        self,
                        f"Stock insuffisant pour « {line.name} » : "
                        f"disponible {format_quantity(stock)}, demandé {format_quantity(qty)}.",
                        "Stock insuffisant",
                    )
                    self._render_cart()
                    return
            line.quantity = qty
            self._render_cart()

        elif item.column() == self.COL_PRICE:
            if not self.state.can(perms.MANAGE_PRICES):
                warn(self, "Vous n'avez pas l'autorisation de modifier les prix.")
                self._render_cart()
                return
            new_price = to_float(item.text())
            if new_price <= 0:
                self._render_cart()
                return
            min_price = self._min_price_for_product(line.product_id)
            if min_price > 0 and new_price < min_price:
                warn(
                    self,
                    f"Prix minimum pour « {line.name} » : "
                    f"{format_money(min_price, settings_service.get_currency())}.",
                    "Prix minimum",
                )
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

    def _cart_subtotal(self) -> float:
        return round(sum(line.total for line in self.cart), 2)

    def _discount_value(self) -> float:
        return min(self._cart_subtotal(), float(self.discount_input.value()))

    def _cart_total(self) -> float:
        return max(0.0, self._cart_subtotal() - self._discount_value())

    def _update_total(self) -> None:
        subtotal = self._cart_subtotal()
        # Plafond remise caissier (% du panier).
        from app.services.cash_controls import max_discount_amount

        capped = max_discount_amount(subtotal, self.state.current_user)
        if capped is not None and self.discount_input.value() > capped:
            self.discount_input.blockSignals(True)
            self.discount_input.setValue(capped)
            self.discount_input.blockSignals(False)
            if subtotal > 0:
                warn(
                    self,
                    f"Remise plafonnée à {capped:g} pour le rôle caissier.",
                    "Remise plafonnée",
                )
        if self.discount_input.value() > subtotal:
            self.discount_input.blockSignals(True)
            self.discount_input.setValue(subtotal)
            self.discount_input.blockSignals(False)
            if subtotal > 0:
                warn(
                    self,
                    "La remise ne peut pas dépasser le sous-total du panier.",
                    "Remise plafonnée",
                )
        currency = settings_service.get_currency()
        self.total_label.setText(f"Total : {format_money(self._cart_total(), currency)}")

    def _clear_cart(self) -> None:
        pending_id = self._pending_sale_id
        self._pending_sale_id = None
        if pending_id:
            SaleController.delete_pending(pending_id, user_id=self.state.user_id)
        self.cart.clear()
        self.discount_input.setValue(0)
        self.client_search.clear()
        self._render_cart()

    def _hold_sale(self) -> None:
        if not self.cart:
            warn(self, "Le panier est vide.")
            return
        if self.discount_input.value() > 0 and not self.state.can(perms.APPLY_DISCOUNT):
            warn(self, "Vous n'avez pas l'autorisation d'appliquer une remise.")
            return
        try:
            sale = SaleController.hold_sale(
                list(self.cart),
                discount=self._discount_value(),
                client_id=self._current_client_id(),
                user_id=self.state.user_id,
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        info(self, f"Vente mise en attente : {sale.ticket_number}")
        self._clear_cart()
        self._reload_products()

    def _resume_pending(self) -> None:
        # Caissier : uniquement ses propres ventes en attente.
        pending_user = self.state.user_id
        allow_any = getattr(self.state.current_user, "role", "") in (
            perms.ROLE_ADMIN,
            perms.ROLE_MANAGER,
        )
        pending = SaleController.list_pending(
            user_id=None if allow_any else pending_user
        )
        if not pending:
            warn(self, "Aucune vente en attente.")
            return
        labels = [
            f"{s.ticket_number} — {float(s.total):g} ({len(s.items)} article(s))"
            for s in pending
        ]
        choice, ok = QInputDialog.getItem(
            self, "Reprendre une vente", "Vente en attente :", labels, 0, False
        )
        if not ok:
            return
        sale = pending[labels.index(choice)]
        try:
            lines, discount, client_id = SaleController.claim_pending(
                sale.id, user_id=self.state.user_id, allow_any=allow_any
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.cart = lines
        self.discount_input.setValue(discount)
        self._pending_sale_id = None
        if client_id is not None:
            self.client_search.set_client(client_id)
        self._render_cart()

    # --- Encaissement ------------------------------------------------------
    def _checkout(self) -> None:
        if not self.cart:
            warn(self, "Le panier est vide.")
            return
        total = self._cart_total()
        client_id: Optional[int] = self._current_client_id()
        phone = self._current_client_phone()
        dialog = PaymentDialog(
            total,
            client_id=client_id,
            client_phone=phone,
            allow_credit=self.state.can(perms.SELL_ON_CREDIT),
            max_credit=self._cashier_max_credit(),
            parent=self,
        )
        if not dialog.exec():
            return
        client_id = dialog.result_client_id or client_id
        if client_id is not None:
            self.client_search.set_client(client_id)
        try:
            credit_requested = dialog.use_credit or any(
                p.method == config.PAYMENT_METHOD_CREDIT
                for p in dialog.result_payments
            )
            if credit_requested and not self.state.can(perms.SELL_ON_CREDIT):
                warn(self, "Vous n'avez pas l'autorisation de vendre à crédit.")
                return
            if self.discount_input.value() > 0 and not self.state.can(
                perms.APPLY_DISCOUNT
            ):
                warn(self, "Vous n'avez pas l'autorisation d'appliquer une remise.")
                return
            result = SaleController.create_sale(
                lines=list(self.cart),
                payments=dialog.result_payments,
                amount_received=dialog.amount_received,
                discount=self._discount_value(),
                client_id=client_id,
                user_id=self.state.user_id,
                allow_credit=credit_requested,
                debt_due_date=dialog.credit_due_date,
            )
        except InsufficientPaymentError as exc:
            warn(self, str(exc), "Paiement insuffisant")
            return
        except InsufficientStockError as exc:
            warn(self, str(exc), "Stock insuffisant")
            self._reload_products()
            return
        except BelowMinPriceError as exc:
            warn(self, str(exc), "Prix minimum")
            return
        except ValueError as exc:
            warn(self, str(exc))
            return

        if self._pending_sale_id:
            SaleController.delete_pending(
                self._pending_sale_id, user_id=self.state.user_id
            )
            self._pending_sale_id = None

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
            # Après vente : proposer d'enregistrer (pas d'impression auto).
            TicketDialog(sale, self, auto_print=False).exec()

        self._clear_cart()
        self._reload_products()
        self.state.notify_data_changed()
