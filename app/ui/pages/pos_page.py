"""Module Caisse : interface de vente rapide."""
from __future__ import annotations
from typing import Dict, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QPushButton, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app import config
from app.controllers.client_controller import ClientController
from app.controllers.product_controller import ProductController
from app.controllers.sale_controller import CartLine, BelowMinPriceError, InsufficientPaymentError, InsufficientStockError, SaleController
from app.i18n import t
from app.services import audit_service, permissions as perms, product_profile, settings_service
from app.ui.dialogs.free_amount_dialog import FreeAmountDialog
from app.ui.dialogs.payment_dialog import PaymentDialog
from app.ui.dialogs.price_change_dialog import PriceChangeDialog
from app.ui.dialogs.ticket_dialog import TicketDialog
from app.ui.responsive import LayoutProfile
from app.ui.state import AppState
from app.ui.widgets.client_search import ClientSearchField
from app.ui.widgets.helpers import info, page_title, warn
from app.ui.widgets.pos_catalog_panel import PosCatalogPanel
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
        self._chip_buttons: list = []
        self._grid_product_ids: list[int] = []
        self._root = QHBoxLayout(self)
        self._root.setContentsMargins(12, 12, 12, 12)
        self._root.setSpacing(12)
        self._maquis_mode = product_profile.is_maquis()
        self._catalog = PosCatalogPanel(self)
        if self._maquis_mode:
            self._catalog.product_chosen.connect(self._maquis_product_tap)
        else:
            self._catalog.product_chosen.connect(self._add_product)
        self._waitress_combo: Optional[QComboBox] = None
        self._table_combo: Optional[QComboBox] = None
        self._save_order_btn: Optional[QPushButton] = None
        self._pay_button: Optional[QPushButton] = None
        self._cart_panel = self._build_cart()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_host = QWidget()
        self._scroll_layout = QHBoxLayout(self._scroll_host)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(12)
        self._scroll_layout.addWidget(self._catalog, 5)  # PosCatalogPanel
        self._scroll_layout.addWidget(self._cart_panel, 4)
        self._scroll.setWidget(self._scroll_host)
        self._root.addWidget(self._scroll, 1)
        self.state.layout_changed.connect(self._on_layout_changed)
        if self.state.layout is not None:
            self._on_layout_changed(self.state.layout)
        if self._maquis_mode:
            self._apply_maquis_caisse_ui()

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
            self._catalog.setMinimumHeight(cat_min)  # type: ignore[union-attr]
            self._cart_panel.setMinimumHeight(cart_min)
            self._catalog.setMinimumWidth(0)
            self._cart_panel.setMinimumWidth(0)
        else:
            self._scroll_layout.setStretch(0, 5)
            self._scroll_layout.setStretch(1, 4)
            self._catalog.setMinimumHeight(0)
            self._cart_panel.setMinimumHeight(0)
            self._catalog.setMinimumWidth(280)  # type: ignore[union-attr]
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
        if isinstance(self._catalog, PosCatalogPanel):
            self._catalog.apply_layout_profile(profile)

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
        self._client_row_widget = QWidget()
        client_row = QHBoxLayout(self._client_row_widget)
        client_row.setContentsMargins(0, 0, 0, 0)
        client_row.addWidget(QLabel(t('pos.client')))
        self.client_search = ClientSearchField(placeholder='Tapez un nom ou un téléphone…')
        self.client_search.client_selected.connect(self._on_client_selected)
        client_row.addWidget(self.client_search, 1)
        layout.addWidget(self._client_row_widget)
        self._client_hint = QLabel(t('Suggestions au fur et à mesure. Sélectionnez le client pour facturer ou mettre en dette.'))
        self._client_hint.setWordWrap(True)
        self._client_hint.setStyleSheet('color: #64748b; font-size: 12px;')
        layout.addWidget(self._client_hint)
        self.cart_table = QTableWidget(0, 5)
        self.cart_table.setHorizontalHeaderLabels([t('Produit'), t('Qté'), t('Prix U.'), t('Total'), ''])
        self.cart_table.horizontalHeader().setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.cart_table.setColumnWidth(self.COL_QTY, 70)
        self.cart_table.setColumnWidth(self.COL_PRICE, 100)
        self.cart_table.setColumnWidth(self.COL_TOTAL, 110)
        self.cart_table.setColumnWidth(self.COL_DEL, 44)
        self.cart_table.itemChanged.connect(self._on_cart_edited)
        if self._maquis_mode:
            self.cart_table.cellDoubleClicked.connect(self._maquis_edit_qty)
        layout.addWidget(self.cart_table)
        self._discount_row_widget = QWidget()
        discount_row = QHBoxLayout(self._discount_row_widget)
        discount_row.setContentsMargins(0, 0, 0, 0)
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
        layout.addWidget(self._discount_row_widget)
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
        self._pending_row = QWidget()
        self._pending_row.setLayout(pending_row)
        layout.addWidget(self._pending_row)
        pay_button = QPushButton(t('pos.checkout'))
        pay_button.setObjectName('Success')
        pay_button.setMinimumHeight(52)
        pay_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        pay_button.clicked.connect(self._checkout)
        layout.addWidget(pay_button)
        self._pay_button = pay_button
        if product_profile.is_maquis():
            save_btn = QPushButton(t("Enregistrer commande"))
            save_btn.setObjectName("MaquisEnregistrer")
            save_btn.clicked.connect(self._save_maquis_order)
            layout.insertWidget(layout.indexOf(pay_button), save_btn)
            self._save_order_btn = save_btn
            pay_button.setText(t("Encaisser"))
            pay_button.setObjectName("MaquisEncaisser")
            pay_button.setMinimumHeight(56)
        return panel

    def _apply_maquis_caisse_ui(self) -> None:
        """Alignement écran Caisse sur l'app tablette (serveuse, table, pas de ticket auto)."""
        self.setObjectName("MaquisCaissePage")
        bar = QHBoxLayout()
        self._waitress_combo = QComboBox()
        self._waitress_combo.setMinimumHeight(40)
        self._waitress_combo.addItem(t("Aucune"), None)
        from sqlalchemy import select

        from app.database.connection import session_scope
        from app.models.user import User

        with session_scope() as session:
            users = list(
                session.scalars(
                    select(User)
                    .where(User.is_active.is_(True))
                    .order_by(User.full_name)
                ).all()
            )
        for u in users:
            if u.is_waitress or u.role in (perms.ROLE_CASHIER, perms.ROLE_MANAGER):
                self._waitress_combo.addItem(u.full_name or u.username, u.id)
        self._table_combo = QComboBox()
        self._table_combo.setMinimumHeight(40)
        self._table_combo.addItem(t("Aucune"), None)
        from app.services.table_service import TableService

        from app.services.maquis_settings import tables_enabled

        self._tables_enabled = tables_enabled()
        if self._tables_enabled:
            for table in TableService.list():
                self._table_combo.addItem(table.display_name, table.id)
        else:
            self._table_combo.setEnabled(False)
            self._table_combo.addItem(t("Tables désactivées"), None)
        bar.addWidget(QLabel(t("Serveuse")))
        bar.addWidget(self._waitress_combo, 1)
        bar.addWidget(QLabel(t("Table")))
        bar.addWidget(self._table_combo, 1)
        host = QWidget()
        host.setLayout(bar)
        cat_layout = self._catalog.layout()
        if cat_layout is not None:
            cat_layout.insertWidget(1, host)
        # Masquer uniquement les blocs boutique (pas le panneau panier entier)
        self._client_row_widget.setVisible(False)
        self._client_hint.setVisible(False)
        self._discount_row_widget.setVisible(False)
        # Fidélité bénéfices aussi sur Maquis — visible si activée
        self._loyalty_row_widget.setVisible(product_profile.supports_profit_loyalty())
        if hasattr(self, "_pending_row"):
            self._pending_row.setVisible(False)
        from app.services.maquis_cart_store import load_cart

        saved = load_cart(self.state.user_id)
        if saved:
            self.cart = saved
            self._render_cart()

    def _maquis_edit_qty(self, row: int, column: int) -> None:
        """Double-clic quantité → pavé tactile (parité tablette)."""
        if column != self.COL_QTY or row < 0 or row >= len(self.cart):
            return
        line = self.cart[row]
        if line.free_amount or line.loyalty_reward:
            return
        from app.ui.dialogs.quantity_pad_dialog import QuantityPadDialog

        dlg = QuantityPadDialog(line.name, parent=self, initial=float(line.quantity))
        if not dlg.exec() or dlg.quantity <= 0:
            return
        if line.product_id:
            stock = self._available_stock(line.product_id, exclude_cart=True)
            if dlg.quantity > stock + 0.0001:
                warn(
                    self,
                    t("Stock insuffisant"),
                    t("Stock insuffisant"),
                )
                return
        line.quantity = dlg.quantity
        self._render_cart()

    def _maquis_product_tap(self, product) -> None:
        from app.ui.dialogs.quantity_pad_dialog import QuantityPadDialog

        if getattr(product, "free_amount_sale", False):
            self._add_product(product)
            return
        dlg = QuantityPadDialog(product.name, parent=self)
        if not dlg.exec() or dlg.quantity <= 0:
            return
        min_price = float(product.min_price or 0)
        sale_price = float(product.sale_price)
        if min_price > 0 and sale_price < min_price:
            warn(self, t("Prix minimum"))
            return
        available = self._available_stock(product.id)
        if available + 0.0001 < dlg.quantity:
            warn(self, t("Stock insuffisant"), t("Stock insuffisant"))
            return
        for line in self.cart:
            if line.product_id == product.id and (not line.free_amount) and (not line.loyalty_reward):
                line.quantity += dlg.quantity
                self._render_cart()
                return
        self.cart.append(
            CartLine(
                product_id=product.id,
                name=product.name,
                unit_price=sale_price,
                quantity=dlg.quantity,
                purchase_price=float(product.purchase_price),
            )
        )
        self._render_cart()

    def _maquis_table_context(self) -> tuple[Optional[int], str, Optional[int], str]:
        wid = self._waitress_combo.currentData() if self._waitress_combo else None
        wname = self._waitress_combo.currentText() if self._waitress_combo and wid else ""
        tid = self._table_combo.currentData() if self._table_combo else None
        tlabel = self._table_combo.currentText() if self._table_combo and tid else ""
        return tid, tlabel, wid, wname

    def _save_maquis_order(self) -> None:
        if not self.cart:
            warn(self, t("Le panier est vide."))
            return
        tid, tlabel, wid, wname = self._maquis_table_context()
        try:
            from app.services.order_service import OrderService

            order = OrderService.upsert_cart_for_table(
                self.cart,
                table_id=tid,
                table_label=tlabel,
                waitress_id=wid,
                waitress_name=wname,
                opened_by=self.state.user_id,
            )
            from app.printers.ticket.options import is_kitchen_ticket_enabled
            from app.services.maquis_kitchen import print_kitchen_for_order
            from app.services.maquis_settings import kitchen_prompt_after_save
            from app.ui.dialogs.saved_order_prompt_dialog import SavedOrderPromptDialog

            user = getattr(self.state.current_user, "username", "") or ""
            print_enabled = is_kitchen_ticket_enabled() and kitchen_prompt_after_save()
            print_message = None
            if print_enabled:
                ok, print_message = print_kitchen_for_order(
                    order.id, cashier_name=user
                )
                if ok:
                    print_message = print_message or t("Ticket imprimé")
            if print_enabled or is_kitchen_ticket_enabled():
                prompt = SavedOrderPromptDialog(
                    order.public_id,
                    is_kitchen_ticket_enabled(),
                    print_message or "",
                    parent=self,
                )
                prompt.exec()
                if prompt.reprint_requested:
                    print_kitchen_for_order(order.id, cashier_name=user)
            self._clear_cart()
            self.state.notify_data_changed()
        except Exception as exc:
            warn(self, str(exc))

    def refresh(self) -> None:
        if isinstance(self._catalog, PosCatalogPanel):
            self._catalog.refresh()
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
        self.cart_table.setFont(font)
        self.cart_table.verticalHeader().setDefaultSectionSize(row_h)
        self.cart_table.verticalHeader().setVisible(False)
        for row in range(self.cart_table.rowCount()):
            for col in (self.COL_NAME, self.COL_PRICE, self.COL_TOTAL, self.COL_QTY):
                item = self.cart_table.item(row, col)
                if item is not None:
                    item.setFont(price_font if col != self.COL_NAME else font)

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
        if not isinstance(self._catalog, PosCatalogPanel):
            return
        product = self._catalog.selected_product()
        if not product:
            warn(self, t('Sélectionnez un produit du catalogue à offrir.'))
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
                if self._maquis_mode:
                    qty_item.setFlags(qty_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    qty_item.setToolTip(t("Double-clic pour modifier la quantité (pavé)"))
                price_item = QTableWidgetItem(f'{float(line.unit_price):g}')
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if self._maquis_mode or not self.state.can(perms.MANAGE_PRICES):
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
        if self._maquis_mode:
            from app.services.maquis_cart_store import save_cart

            save_cart(self.cart, self.state.user_id)

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
        if self._maquis_mode:
            from app.services.maquis_cart_store import clear_cart

            clear_cart(self.state.user_id)
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

    def _checkout_maquis(self) -> None:
        total = self._cart_total()
        if total <= 0:
            warn(self, t("Montant total invalide"))
            return
        from app.services.maquis_payment_flow import (
            apply_payment_to_order,
            run_maquis_payment,
        )
        from app.services.order_service import OrderService

        pay = run_maquis_payment(total, self, allow_partial=False, state=self.state)
        if not pay:
            return
        tid, tlabel, wid, wname = self._maquis_table_context()
        try:
            order = OrderService.upsert_cart_for_table(
                list(self.cart),
                table_id=tid,
                table_label=tlabel,
                waitress_id=wid,
                waitress_name=wname,
                opened_by=self.state.user_id,
            )
            user = getattr(self.state.current_user, "username", "") or ""
            apply_payment_to_order(
                order.id,
                pay,
                user_id=self.state.user_id,
                user_name=user,
                remaining_before=total,
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        except InsufficientStockError as exc:
            warn(self, str(exc), t("Stock insuffisant"))
            return
        currency = settings_service.get_currency()
        info(
            self,
            t("Commande {id} payée").format(id=order.public_id)
            + f"\n{t('Monnaie rendue')} : {format_money(pay.change_amount, currency)}",
            t("Encaissement"),
        )
        self._clear_cart()
        if isinstance(self._catalog, PosCatalogPanel):
            self._catalog.refresh()
        self.state.notify_data_changed()

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
        if self._maquis_mode:
            self._checkout_maquis()
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
        if not self._maquis_mode:
            sale = SaleController.get(result.sale_id)
            if sale:
                if result.loyalty_credit_remaining is not None:
                    sale.loyalty_credit_remaining = result.loyalty_credit_remaining
                TicketDialog(sale, self, auto_print=False).exec()
        self._clear_cart()
        if isinstance(self._catalog, PosCatalogPanel):
            self._catalog.refresh()
        self.state.notify_data_changed()
