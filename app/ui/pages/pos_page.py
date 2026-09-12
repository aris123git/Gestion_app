"""Module Caisse : interface de vente rapide."""
from __future__ import annotations
from typing import Dict, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget
from app import config
from app.controllers.client_controller import ClientController
from app.controllers.product_controller import ProductController
from app.controllers.sale_controller import CartLine, BelowMinPriceError, InsufficientPaymentError, InsufficientStockError, SaleController
from app.i18n import t
from app.services import audit_service, catalog_features, permissions as perms, settings_service
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
    COL_NAME, COL_QTY, COL_PRICE, COL_TOTAL, COL_DEL = range(5)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.cart: List[CartLine] = []
        self._updating = False
        self._client_map: Dict[int, int] = {}
        self._pending_sale_id: Optional[int] = None
        self._chip_buttons: list[QToolButton] = []
        self._grid_product_ids: list[int] = []
        self._root = QHBoxLayout(self)
        self._root.setContentsMargins(12, 12, 12, 12)
        self._root.setSpacing(12)
        self._catalog = self._build_catalog()
        self._cart_panel = self._build_cart()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        margins = 6 if profile.density == 'compact' else 10 if profile.is_narrow else 12
        self._root.setContentsMargins(margins, margins, margins, margins)
        spacing = 8 if profile.is_short or profile.is_narrow else 12
        self._root.setSpacing(spacing)
        self._scroll_layout.setSpacing(spacing)
        stack = profile.stack_panels
        direction = QHBoxLayout.Direction.TopToBottom if stack else QHBoxLayout.Direction.LeftToRight
        self._scroll_layout.setDirection(direction)
        if stack:
            self._scroll_layout.setStretch(0, 3)
            self._scroll_layout.setStretch(1, 2)
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
            self._catalog.setMinimumWidth(280)
            self._cart_panel.setMinimumWidth(260)
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
        total_px = 20 if profile.density == 'compact' else 22 if profile.is_narrow else 26
        self.total_label.setStyleSheet(f'font-size: {total_px}px; font-weight: 800;')
        if self._pay_button is not None:
            self._pay_button.setMinimumHeight(44 if profile.density != 'comfortable' else 52)
            self._pay_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _build_catalog(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName('Card')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(page_title(t('pos.title')))
        search_row = QHBoxLayout()
        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText(t('pos.barcode'))
        self.barcode_input.returnPressed.connect(self._add_by_barcode)
        search_row.addWidget(self.barcode_input)
        layout.addLayout(search_row)
        filter_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t('pos.search_product'))
        self.search_input.textChanged.connect(self._reload_products)
        self.category_filter = QComboBox()
        self.category_filter.currentIndexChanged.connect(self._reload_products)
        filter_row.addWidget(self.search_input, 3)
        filter_row.addWidget(self.category_filter, 2)
        layout.addLayout(filter_row)
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
        self.category_chips_layout.addStretch(1)
        self.category_chips_scroll.setWidget(self.category_chips_host)
        layout.addWidget(self.category_chips_scroll)
        self.product_table = QTableWidget(0, 3)
        self.product_table.setHorizontalHeaderLabels([t('pos.product'), t('pos.price'), t('pos.stock')])
        self.product_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.product_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.product_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
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
        self.add_to_cart_btn = QPushButton(t('pos.add_to_cart'))
        self.add_to_cart_btn.setObjectName('Primary')
        self.add_to_cart_btn.clicked.connect(self._add_selected_product)
        layout.addWidget(self.add_to_cart_btn)
        self._apply_catalog_mode()
        return panel

    def _apply_catalog_mode(self) -> None:
        """Affiche combo/table ou chips/grille selon les options Paramètres."""
        use_chips = catalog_features.category_browser_enabled()
        use_images = catalog_features.product_images_enabled()
        self.category_filter.setVisible(not use_chips)
        self.category_chips_scroll.setVisible(use_chips)
        self.product_table.setVisible(not use_images)
        self.product_grid_scroll.setVisible(use_images)
        self.add_to_cart_btn.setVisible(not use_images)

    def _build_cart(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName('Card')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(page_title(t('pos.cart')))
        header.addStretch()
        clear = QPushButton(t('pos.clear_cart'))
        clear.setObjectName('Danger')
        clear.clicked.connect(self._clear_cart)
        header.addWidget(clear)
        layout.addLayout(header)
        client_row = QHBoxLayout()
        client_row.addWidget(QLabel(t('pos.client')))
        self.client_search = ClientSearchField(placeholder='Tapez un nom ou un téléphone…')
        self.client_search.client_selected.connect(self._on_client_selected)
        client_row.addWidget(self.client_search, 1)
        layout.addLayout(client_row)
        hint = QLabel(t('Suggestions au fur et à mesure. Sélectionnez le client pour facturer ou mettre en dette.'))
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #64748b; font-size: 12px;')
        layout.addWidget(hint)
        self.cart_table = QTableWidget(0, 5)
        self.cart_table.setHorizontalHeaderLabels([t('Produit'), t('Qté'), t('Prix U.'), t('Total'), ''])
        self.cart_table.horizontalHeader().setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.cart_table.setColumnWidth(self.COL_QTY, 70)
        self.cart_table.setColumnWidth(self.COL_PRICE, 100)
        self.cart_table.setColumnWidth(self.COL_TOTAL, 110)
        self.cart_table.setColumnWidth(self.COL_DEL, 44)
        self.cart_table.itemChanged.connect(self._on_cart_edited)
        layout.addWidget(self.cart_table)
        discount_row = QHBoxLayout()
        discount_row.addWidget(QLabel(t('pos.discount')))
        self.discount_input = QDoubleSpinBox()
        self.discount_input.setRange(0, 0)
        self.discount_input.setDecimals(0)
        self.discount_input.setSingleStep(100)
        self.discount_input.valueChanged.connect(self._update_total)
        if not self.state.can(perms.APPLY_DISCOUNT):
            self.discount_input.setEnabled(False)
            self.discount_input.setToolTip(t("Vous n'avez pas l'autorisation d'appliquer une remise."))
        elif getattr(self.state.current_user, 'role', '') == perms.ROLE_CASHIER:
            from app.services.cash_controls import get_max_discount_percent
            pct = get_max_discount_percent()
            self.discount_input.setToolTip(f'Plafond caissier : {pct:g} % du sous-total')
        discount_row.addWidget(self.discount_input)
        self.discount_hint = QLabel('')
        self.discount_hint.setStyleSheet('color: #b45309; font-size: 12px;')
        discount_row.addWidget(self.discount_hint, 1)
        layout.addLayout(discount_row)
        loyalty_row = QHBoxLayout()
        self.loyalty_hint = QLabel('')
        self.loyalty_hint.setStyleSheet('color: #64748b; font-size: 12px;')
        self.loyalty_hint.setWordWrap(True)
        loyalty_row.addWidget(self.loyalty_hint, 1)
        self.loyalty_offer_btn = QPushButton(t('Offrir produit'))
        self.loyalty_offer_btn.setToolTip(t('Ajoute le produit sélectionné du catalogue comme produit offert (fidélité). Pas de remise en argent — uniquement un article boutique.'))
        self.loyalty_offer_btn.setEnabled(False)
        self.loyalty_offer_btn.clicked.connect(self._offer_selected_loyalty_product)
        loyalty_row.addWidget(self.loyalty_offer_btn)
        self._loyalty_row_widget = QWidget()
        self._loyalty_row_widget.setLayout(loyalty_row)
        layout.addWidget(self._loyalty_row_widget)
        from app.services import product_profile
        self._loyalty_row_widget.setVisible(product_profile.supports_profit_loyalty())
        self.total_label = QLabel(t('Total : 0'))
        self.total_label.setStyleSheet('font-size: 26px; font-weight: 800;')
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.total_label)
        pending_row = QHBoxLayout()
        hold_btn = QPushButton(t('pos.hold'))
        hold_btn.clicked.connect(self._hold_sale)
        resume_btn = QPushButton(t('pos.resume'))
        resume_btn.clicked.connect(self._resume_pending)
        pending_row.addWidget(hold_btn)
        pending_row.addWidget(resume_btn)
        layout.addLayout(pending_row)
        pay_button = QPushButton(t('pos.checkout'))
        pay_button.setObjectName('Success')
        pay_button.setMinimumHeight(52)
        pay_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        pay_button.clicked.connect(self._checkout)
        layout.addWidget(pay_button)
        self._pay_button = pay_button
        return panel

    def refresh(self) -> None:
        self._apply_catalog_mode()
        self._reload_categories()
        self._reload_products()
        self._reload_clients()
        self._apply_large_text()

    def _apply_large_text(self) -> None:
        """Agrandit noms/prix catalogue + panier si activé dans Paramètres."""
        large = settings_service.get_setting('pos_catalog_large_text', '0') == '1'
        size_key = settings_service.get_setting('pos_catalog_text_size', 'large')
        if large:
            pt = 22 if size_key == 'xlarge' else 18
            row_h = 46 if size_key == 'xlarge' else 38
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
        self.category_filter.addItem(t('pos.all_categories'), None)
        categories = CategoryController.list()
        for category in categories:
            self.category_filter.addItem(category.name, category.id)
        index = self.category_filter.findData(current)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)
        self._rebuild_category_chips(categories, current)

    def _reload_clients(self, select_id: Optional[int]=None) -> None:
        if select_id is not None:
            self.client_search.set_client(select_id)

    def _on_client_selected(self, client_id) -> None:
        self._refresh_loyalty_credit(client_id)

    def _current_client_id(self) -> Optional[int]:
        return self.client_search.client_id

    def _loyalty_credit_used_in_cart(self) -> float:
        return round(sum((float(line.reward_value) for line in self.cart)), 2)

    def _loyalty_credit_remaining_for_cart(self) -> float:
        from app.services.profit_loyalty_service import ProfitLoyaltyService
        cid = self._current_client_id()
        if not cid or not ProfitLoyaltyService.is_enabled():
            return 0.0
        balance = ProfitLoyaltyService.credit_balance(int(cid))
        return max(0.0, balance - self._loyalty_credit_used_in_cart())

    def _refresh_loyalty_credit(self, client_id=None) -> None:
        from app.services.profit_loyalty_service import ProfitLoyaltyService
        cid = client_id if client_id is not None else self._current_client_id()
        currency = settings_service.get_currency()
        if not cid or not ProfitLoyaltyService.is_enabled():
            self.loyalty_offer_btn.setEnabled(False)
            self.loyalty_hint.setText('Sélectionnez un client pour offrir un produit fidélité.' if ProfitLoyaltyService.is_enabled() else 'Fidélité bénéfices désactivée (Paramètres admin).')
            self._update_total()
            return
        balance = ProfitLoyaltyService.credit_balance(int(cid))
        used = self._loyalty_credit_used_in_cart()
        left = max(0.0, balance - used)
        self.loyalty_offer_btn.setEnabled(left > 0.01)
        if balance <= 0.01:
            self.loyalty_hint.setText('Pas encore de crédit (seuil de bénéfice non atteint).')
        else:
            self.loyalty_hint.setText(f'Crédit fidélité : {format_money(balance, currency)}' + (f' — utilisé panier {format_money(used, currency)}' if used > 0.01 else '') + f" — reste {format_money(left, currency)} (produit boutique uniquement, pas d'argent).")
        self._update_total()

    def _offer_selected_loyalty_product(self) -> None:
        """Offre le produit catalogue sélectionné (fidélité = article, pas d'argent)."""
        from app.services.profit_loyalty_service import ProfitLoyaltyService
        if not self._current_client_id():
            warn(self, t("Sélectionnez d'abord le client."))
            return
        if not ProfitLoyaltyService.is_enabled():
            warn(self, t('La fidélité bénéfices est désactivée.'))
            return
        row = self.product_table.currentRow()
        if row < 0:
            warn(self, t('Sélectionnez un produit du catalogue à offrir.'))
            return
        item = self.product_table.item(row, 0)
        if item is None:
            return
        product_id = item.data(Qt.ItemDataRole.UserRole)
        product = ProductController.get(product_id) if product_id else None
        if not product:
            warn(self, t('Produit introuvable.'))
            return
        if getattr(product, 'free_amount_sale', False):
            warn(self, t('Les ventes au montant libre ne peuvent pas être offertes en fidélité. Choisissez un produit à prix fixe (boisson, frite…).'))
            return
        price = float(product.sale_price or 0)
        if price <= 0:
            warn(self, t("Ce produit n'a pas de prix de vente."))
            return
        left = self._loyalty_credit_remaining_for_cart()
        if price > left + 0.009:
            currency = settings_service.get_currency()
            warn(self, f'Crédit insuffisant pour offrir « {product.name} » ({format_money(price, currency)} > {format_money(left, currency)} restants).')
            return
        available = self._available_stock(product.id)
        if available + 0.0001 < 1.0:
            warn(self, f'Stock insuffisant pour « {product.name} ».', t('Stock insuffisant'))
            return
        for line in self.cart:
            if line.loyalty_reward and line.product_id == product.id and (not line.free_amount):
                extra = float(product.sale_price)
                if extra > self._loyalty_credit_remaining_for_cart() + 0.009:
                    warn(self, t('Crédit fidélité insuffisant pour une unité de plus.'))
                    return
                line.quantity += 1
                self._render_cart()
                return
        self.cart.append(CartLine(product_id=product.id, name=product.name, unit_price=float(product.sale_price), quantity=1, purchase_price=float(product.purchase_price), loyalty_reward=True))
        self._render_cart()

    def _cashier_max_credit(self) -> Optional[float]:
        from app.services.cash_controls import limits_for_user
        _, max_credit = limits_for_user(self.state.current_user)
        return max_credit

    def _current_client_phone(self) -> str:
        client_id = self._current_client_id()
        if client_id:
            client = ClientController.get(client_id)
            if client:
                return (client.phone or client.phone2 or '').strip()
        text = self.client_search.text()
        if text and any((ch.isdigit() for ch in text)):
            return ''.join((ch for ch in text if ch.isdigit() or ch == '+'))
        return ''

    def _selected_category_id(self):
        return self.category_filter.currentData()

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
            btn.setStyleSheet('QToolButton { padding: 6px 14px; border-radius: 18px; border: 1px solid #cbd5e1; background: #f8fafc; }QToolButton:checked { background: #2563eb; color: white; border-color: #2563eb; }')
            btn.clicked.connect(lambda _=False, cid=cat_id: self._select_category_chip(cid))
            self.category_chips_layout.addWidget(btn)
            self._chip_buttons.append(btn)
        make_chip(t('pos.all_categories'), None)
        for category in categories:
            tip = (category.description or '').strip()
            btn_label = category.name
            make_chip(btn_label, category.id)
            if tip:
                self._chip_buttons[-1].setToolTip(tip)
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
        card.setObjectName('ProductCard')
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedSize(148, 180)
        card.setStyleSheet('#ProductCard { border: 1px solid #e2e8f0; border-radius: 10px; background: #ffffff; }#ProductCard:hover { border: 2px solid #2563eb; }')
        box = QVBoxLayout(card)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(4)
        img = QLabel()
        img.setFixedSize(128, 96)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setStyleSheet('background: #f1f5f9; border-radius: 6px; color: #94a3b8;')
        path = str(getattr(product, 'image_path', '') or '')
        pix = QPixmap(path) if path else QPixmap()
        if not pix.isNull():
            img.setPixmap(pix.scaled(128, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            img.setText('•')
        box.addWidget(img, alignment=Qt.AlignmentFlag.AlignCenter)
        name = QLabel(product.name)
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet('font-weight: 600; font-size: 12px;')
        box.addWidget(name)
        if getattr(product, 'free_amount_sale', False):
            price_txt = f'réf. {format_money(product.sale_price, currency)}' if float(product.sale_price or 0) > 0 else 'montant libre'
        else:
            price_txt = format_money(product.sale_price, currency)
        price = QLabel(price_txt)
        price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        price.setStyleSheet('color: #0f172a; font-weight: 700;')
        box.addWidget(price)
        pid = product.id

        def _click(_event=None, product_id=pid):
            product_obj = ProductController.get(product_id)
            if product_obj:
                self._add_product(product_obj)
        card.mousePressEvent = _click
        return card

    def _reload_products(self) -> None:
        products = ProductController.list(search=self.search_input.text().strip(), category_id=self.category_filter.currentData())
        currency = settings_service.get_currency()
        self.product_table.setRowCount(len(products))
        for row, product in enumerate(products):
            label = product.name
            if getattr(product, 'free_amount_sale', False):
                label = f'{product.name} · montant libre'
            name_item = QTableWidgetItem(label)
            name_item.setData(Qt.ItemDataRole.UserRole, product.id)
            self.product_table.setItem(row, 0, name_item)
            if getattr(product, 'free_amount_sale', False):
                price_txt = f'réf. {format_money(product.sale_price, currency)}/kg' if float(product.sale_price or 0) > 0 else 'montant libre'
            else:
                price_txt = format_money(product.sale_price, currency)
            self.product_table.setItem(row, 1, QTableWidgetItem(price_txt))
            stock_item = QTableWidgetItem(f'{format_quantity(product.quantity)} {product.unit_name}'.strip())
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
        self._add_product(product)

    def _add_selected_product(self) -> None:
        row = self.product_table.currentRow()
        if row < 0:
            return
        product_id = self.product_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        product = ProductController.get(product_id)
        if product:
            self._add_product(product)

    def _available_stock(self, product_id: int, exclude_cart: bool=False) -> float:
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
        if getattr(product, 'free_amount_sale', False):
            self._add_free_amount_product(product)
            return
        min_price = float(product.min_price or 0)
        sale_price = float(product.sale_price)
        if min_price > 0 and sale_price < min_price:
            warn(self, f"Impossible d'ajouter « {product.name} » : le prix de vente {format_money(sale_price, settings_service.get_currency())} est inférieur au prix minimum {format_money(min_price, settings_service.get_currency())}.", t('Prix minimum'))
            return
        available = self._available_stock(product.id)
        requested = 1.0
        if available + 0.0001 < requested:
            warn(self, f'Stock insuffisant pour « {product.name} » : disponible {format_quantity(available)}, demandé {format_quantity(requested)}.', t('Stock insuffisant'))
            return
        for line in self.cart:
            if line.product_id == product.id and (not line.free_amount) and (not line.loyalty_reward):
                line.quantity += 1
                self._render_cart()
                return
        self.cart.append(CartLine(product_id=product.id, name=product.name, unit_price=float(product.sale_price), quantity=1, purchase_price=float(product.purchase_price)))
        self._render_cart()

    def _add_free_amount_product(self, product) -> None:
        """Ajoute une ligne au montant demandé (ex. 300 F de chinchard)."""
        sale_price = float(product.sale_price or 0)
        if sale_price <= 0:
            warn(self, f'« {product.name} » : définissez un prix de vente de référence (ex. F/kg) pour estimer la marge.')
            return
        available = self._available_stock(product.id)
        if available + 0.0001 <= 0:
            warn(self, f'Stock insuffisant pour « {product.name} » : disponible {format_quantity(available)}.', t('Stock insuffisant'))
            return
        dialog = FreeAmountDialog(product.name, sale_price, parent=self)
        if not dialog.exec() or not dialog.amount:
            return
        amount = float(dialog.amount)
        from app.services import cash_controls
        if getattr(self.state.current_user, 'role', '') == perms.ROLE_CASHIER and amount > cash_controls.get_max_free_amount() + 0.009:
            warn(self, f'Montant libre trop élevé pour un caissier (max {cash_controls.get_max_free_amount():g} {settings_service.get_currency()}).')
            return
        estimated_qty = amount / sale_price
        pack = float(getattr(product, 'pack_content', 0) or 0)
        cost_per_unit = float(product.cost_per_sale_unit)
        stock_needed = round(estimated_qty / pack, 6) if pack > 0 else estimated_qty
        if stock_needed > available + 0.0001:
            warn(self, f'Stock insuffisant pour « {product.name} » : disponible {format_quantity(available)} {product.unit_name or 'unité'}(s), besoin estimé {format_quantity(stock_needed)}.', t('Stock insuffisant'))
            return
        currency = settings_service.get_currency()
        display_name = f'{product.name} — {format_money(amount, currency)}'
        self.cart.append(CartLine(product_id=product.id, name=display_name, unit_price=sale_price, quantity=estimated_qty, purchase_price=cost_per_unit, free_amount=True, amount=amount, pack_content=pack))
        self._render_cart()

    def _render_cart(self) -> None:
        self._updating = True
        currency = settings_service.get_currency()
        self.cart_table.setRowCount(len(self.cart))
        for row, line in enumerate(self.cart):
            name_item = QTableWidgetItem(line.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if line.loyalty_reward:
                name_item = QTableWidgetItem(f'{line.name} (offert)')
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                qty_item = QTableWidgetItem(format_quantity(line.quantity))
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                price_item = QTableWidgetItem(f'{float(line.unit_price):g}')
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                price_item.setFlags(price_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                price_item.setToolTip(t('Valeur catalogue — produit offert (fidélité).'))
                total_item = QTableWidgetItem('OFFERT')
            elif line.free_amount:
                qty_item = QTableWidgetItem(f'≈ {format_quantity(line.quantity)}')
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                qty_item.setFlags(qty_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                qty_item.setToolTip(t('Quantité estimée (montant ÷ prix de référence). Non modifiable.'))
                price_item = QTableWidgetItem(f'{float(line.unit_price):g}/kg')
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                price_item.setFlags(price_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                price_item.setToolTip(t('Prix de référence pour la marge estimée.'))
                total_item = QTableWidgetItem(format_money(line.total, currency))
            else:
                qty_item = QTableWidgetItem(format_quantity(line.quantity))
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                price_item = QTableWidgetItem(f'{float(line.unit_price):g}')
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not self.state.can(perms.MANAGE_PRICES):
                    price_item.setFlags(price_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                total_item = QTableWidgetItem(format_money(line.total, currency))
            total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.cart_table.setItem(row, self.COL_NAME, name_item)
            self.cart_table.setItem(row, self.COL_QTY, qty_item)
            self.cart_table.setItem(row, self.COL_PRICE, price_item)
            self.cart_table.setItem(row, self.COL_TOTAL, total_item)
            delete_button = QPushButton(t('✕'))
            delete_button.setObjectName('Danger')
            delete_button.clicked.connect(lambda _=False, r=row: self._remove_line(r))
            self.cart_table.setCellWidget(row, self.COL_DEL, delete_button)
        self._updating = False
        self._refresh_loyalty_credit()
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
            self._render_cart()
            return
        if item.column() == self.COL_QTY:
            qty = to_float(item.text())
            if qty <= 0:
                self._remove_line(row)
                return
            if line.loyalty_reward:
                unit = float(line.unit_price)
                others = sum((float(l.reward_value) for i, l in enumerate(self.cart) if i != row))
                from app.services.profit_loyalty_service import ProfitLoyaltyService
                cid = self._current_client_id()
                balance = ProfitLoyaltyService.credit_balance(int(cid)) if cid else 0.0
                need = round(unit * qty, 2)
                if need > balance - others + 0.009:
                    warn(self, t('Crédit fidélité insuffisant pour cette quantité.'))
                    self._render_cart()
                    return
            if line.product_id:
                stock = self._available_stock(line.product_id, exclude_cart=True)
                if stock <= 0:
                    warn(self, f'Stock insuffisant : « {line.name} » est en rupture de stock.', t('Stock insuffisant'))
                    self._render_cart()
                    return
                if qty > stock:
                    warn(self, f'Stock insuffisant pour « {line.name} » : disponible {format_quantity(stock)}, demandé {format_quantity(qty)}.', t('Stock insuffisant'))
                    self._render_cart()
                    return
            line.quantity = qty
            self._render_cart()
        elif item.column() == self.COL_PRICE:
            if line.loyalty_reward:
                warn(self, t("Le prix d'un produit offert fidélité n'est pas modifiable."))
                self._render_cart()
                return
            if not self.state.can(perms.MANAGE_PRICES):
                warn(self, t("Vous n'avez pas l'autorisation de modifier les prix."))
                self._render_cart()
                return
            new_price = to_float(item.text())
            if new_price <= 0:
                self._render_cart()
                return
            min_price = self._min_price_for_product(line.product_id)
            if min_price > 0 and new_price < min_price:
                warn(self, f'Prix minimum pour « {line.name} » : {format_money(min_price, settings_service.get_currency())}.', t('Prix minimum'))
                self._render_cart()
                return
            if new_price != float(line.unit_price):
                dialog = PriceChangeDialog(line.name, self)
                if dialog.exec():
                    line.unit_price = new_price
                    if dialog.choice == 'permanent' and line.product_id:
                        ProductController.update_price(line.product_id, new_price)
                        audit_service.log_action('Modification prix', 'Product', f'{line.name} -> {new_price}', self.state.user_id, getattr(self.state.current_user, 'username', ''))
                self._render_cart()

    def _cart_subtotal(self) -> float:
        return round(sum((line.total for line in self.cart)), 2)

    def _discount_ceiling(self) -> float:
        """Plafond actuel de la remise (sous-total × éventuel % caissier)."""
        subtotal = self._cart_subtotal()
        from app.services.cash_controls import max_discount_amount
        capped = max_discount_amount(subtotal, self.state.current_user)
        if capped is None:
            return max(0.0, subtotal)
        return max(0.0, min(subtotal, float(capped)))

    def _discount_value(self) -> float:
        return min(self._discount_ceiling(), float(self.discount_input.value()))

    def _cart_total(self) -> float:
        return max(0.0, self._cart_subtotal() - self._discount_value())

    def _update_total(self) -> None:
        """Met à jour total + plafond remise sans dialogue bloquant.

        Les flèches du spinbox ne doivent jamais ouvrir de QMessageBox :
        on borne le maximum du champ et on affiche un hint non modal.
        """
        ceiling = self._discount_ceiling()
        current = float(self.discount_input.value())
        self.discount_input.blockSignals(True)
        self.discount_input.setMaximum(ceiling)
        if current > ceiling:
            self.discount_input.setValue(ceiling)
            hit_cap = True
        else:
            hit_cap = False
        self.discount_input.blockSignals(False)
        currency = settings_service.get_currency()
        if ceiling <= 0:
            self.discount_hint.setText('')
        elif hit_cap:
            self.discount_hint.setText(f'Max {format_money(ceiling, currency)}')
        else:
            self.discount_hint.setText('')
        self.total_label.setText(f'Total : {format_money(self._cart_total(), currency)}')

    def _clear_cart(self) -> None:
        pending_id = self._pending_sale_id
        self._pending_sale_id = None
        if pending_id:
            SaleController.delete_pending(pending_id, user_id=self.state.user_id)
        self.cart.clear()
        self.discount_input.blockSignals(True)
        self.discount_input.setMaximum(0)
        self.discount_input.setValue(0)
        self.discount_input.blockSignals(False)
        self.discount_hint.setText('')
        self.loyalty_offer_btn.setEnabled(False)
        self.loyalty_hint.setText('')
        self.client_search.clear()
        self._render_cart()

    def _hold_sale(self) -> None:
        if not self.cart:
            warn(self, t('Le panier est vide.'))
            return
        if self.discount_input.value() > 0 and (not self.state.can(perms.APPLY_DISCOUNT)):
            warn(self, t("Vous n'avez pas l'autorisation d'appliquer une remise."))
            return
        try:
            sale = SaleController.hold_sale(list(self.cart), discount=self._discount_value(), client_id=self._current_client_id(), user_id=self.state.user_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        info(self, f'Vente mise en attente : {sale.ticket_number}')
        self._clear_cart()
        self._reload_products()

    def _resume_pending(self) -> None:
        pending_user = self.state.user_id
        allow_any = getattr(self.state.current_user, 'role', '') in (perms.ROLE_ADMIN, perms.ROLE_MANAGER)
        pending = SaleController.list_pending(user_id=None if allow_any else pending_user)
        if not pending:
            warn(self, t('Aucune vente en attente.'))
            return
        labels = [f'{s.ticket_number} — {float(s.total):g} ({len(s.items)} article(s))' for s in pending]
        choice, ok = QInputDialog.getItem(self, 'Reprendre une vente', 'Vente en attente :', labels, 0, False)
        if not ok:
            return
        sale = pending[labels.index(choice)]
        try:
            lines, discount, client_id = SaleController.claim_pending(sale.id, user_id=self.state.user_id, allow_any=allow_any)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.cart = lines
        self.discount_input.blockSignals(True)
        self.discount_input.setMaximum(self._discount_ceiling())
        self.discount_input.setValue(min(float(discount), self.discount_input.maximum()))
        self.discount_input.blockSignals(False)
        self._pending_sale_id = None
        if client_id is not None:
            self.client_search.set_client(client_id)
        self._render_cart()

    def _checkout(self) -> None:
        if not self.cart:
            warn(self, t('Le panier est vide.'))
            return
        total = self._cart_total()
        client_id: Optional[int] = self._current_client_id()
        phone = self._current_client_phone()
        dialog = PaymentDialog(total, client_id=client_id, client_phone=phone, allow_credit=self.state.can(perms.SELL_ON_CREDIT), max_credit=self._cashier_max_credit(), parent=self)
        if not dialog.exec():
            return
        client_id = dialog.result_client_id or client_id
        if client_id is not None:
            self.client_search.set_client(client_id)
        try:
            credit_requested = dialog.use_credit or any((p.method == config.PAYMENT_METHOD_CREDIT for p in dialog.result_payments))
            if credit_requested and (not self.state.can(perms.SELL_ON_CREDIT)):
                warn(self, t("Vous n'avez pas l'autorisation de vendre à crédit."))
                return
            if self.discount_input.value() > 0 and (not self.state.can(perms.APPLY_DISCOUNT)):
                warn(self, t("Vous n'avez pas l'autorisation d'appliquer une remise."))
                return
            result = SaleController.create_sale(lines=list(self.cart), payments=dialog.result_payments, amount_received=dialog.amount_received, discount=self._discount_value(), client_id=client_id, user_id=self.state.user_id, allow_credit=credit_requested, debt_due_date=dialog.credit_due_date, loyalty_credit=0)
        except InsufficientPaymentError as exc:
            warn(self, str(exc), t('Paiement insuffisant'))
            return
        except InsufficientStockError as exc:
            warn(self, str(exc), t('Stock insuffisant'))
            self._reload_products()
            return
        except BelowMinPriceError as exc:
            warn(self, str(exc), t('Prix minimum'))
            return
        except ValueError as exc:
            warn(self, str(exc))
            return
        if self._pending_sale_id:
            SaleController.delete_pending(self._pending_sale_id, user_id=self.state.user_id)
            self._pending_sale_id = None
        audit_service.log_action('Vente', 'Sale', f'{result.ticket_number} total={result.total}', self.state.user_id, getattr(self.state.current_user, 'username', ''))
        currency = settings_service.get_currency()
        info(self, f'Vente enregistrée : {result.ticket_number}\nTotal : {format_money(result.total, currency)}\nMonnaie rendue : {format_money(result.change_due, currency)}', t('Vente réussie'))
        sale = SaleController.get(result.sale_id)
        if sale:
            if result.loyalty_credit_remaining is not None:
                sale.loyalty_credit_remaining = result.loyalty_credit_remaining
            TicketDialog(sale, self, auto_print=False).exec()
        self._clear_cart()
        self._reload_products()
        self.state.notify_data_changed()
