"""Saisie tactile d'une commande de table — Maquis Caisse.

Même composants que la caisse (``TouchCatalog`` + ``TouchTicket``) : la saisie
des produits et l'affichage de l'ardoise sont donc identiques d'un écran à
l'autre. Les articles sont enregistrés au fur et à mesure sur la commande ; le
stock ne bouge qu'à l'encaissement, qui crée une vraie vente.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.controllers.product_controller import ProductController
from app.controllers.sale_controller import (
    BelowMinPriceError,
    InsufficientPaymentError,
    InsufficientStockError,
)
from app.i18n import t
from app.services import permissions as perms
from app.services import settings_service
from app.services.order_service import OrderService
from app.services.table_service import TableService
from app.ui.dialogs.free_amount_dialog import FreeAmountDialog
from app.ui.dialogs.payment_dialog import PaymentDialog
from app.ui.widgets.client_search import ClientSearchField
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, warn
from app.ui.widgets.touch_catalog import TouchCatalog
from app.ui.widgets.touch_ticket import TouchTicket
from app.utils.helpers import format_money, format_quantity


def checkout_order(
    parent,
    state,
    order_id: int,
    *,
    discount: float = 0.0,
    client_id: Optional[int] = None,
) -> bool:
    """Encaisse une commande via le dialogue de paiement de la caisse.

    Retourne True si la commande a été encaissée. Aucune impression n'est
    déclenchée : l'addition et le ticket restent des actions volontaires.
    """
    from app import config

    order = OrderService.get(order_id)
    if order is None:
        warn(parent, t('Commande introuvable.'))
        return False
    if not order.items:
        warn(parent, t('Aucun article sur cette commande.'))
        return False
    currency = settings_service.get_currency()
    subtotal = round(sum(float(item.line_total or 0) for item in order.items), 2)
    discount = max(0.0, min(float(discount or 0), subtotal))
    total = round(subtotal - discount, 2)
    dialog = PaymentDialog(
        total,
        client_id=client_id,
        allow_credit=state.can(perms.SELL_ON_CREDIT),
        parent=parent,
    )
    if not dialog.exec():
        return False
    client_id = dialog.result_client_id or client_id
    credit_requested = dialog.use_credit or any(
        payment.method == config.PAYMENT_METHOD_CREDIT
        for payment in dialog.result_payments
    )
    try:
        result = OrderService.checkout(
            order_id,
            payments=dialog.result_payments,
            amount_received=dialog.amount_received,
            discount=discount,
            client_id=client_id,
            user_id=state.user_id,
            allow_credit=credit_requested,
            debt_due_date=dialog.credit_due_date,
        )
    except InsufficientPaymentError as exc:
        warn(parent, str(exc), t('Paiement insuffisant'))
        return False
    except InsufficientStockError as exc:
        warn(parent, str(exc), t('Stock insuffisant'))
        return False
    except BelowMinPriceError as exc:
        warn(parent, str(exc), t('Prix minimum'))
        return False
    except ValueError as exc:
        warn(parent, str(exc))
        return False
    message = t('Commande encaissée — table libérée.')
    if result is not None:
        message = t(
            'Commande encaissée : {ticket}\nTotal : {total}\nMonnaie rendue : {change}'
        ).format(
            ticket=result.ticket_number,
            total=format_money(result.total, currency),
            change=format_money(result.change_due, currency),
        )
    info(parent, message, t('Encaissement'))
    state.notify_data_changed()
    return True


class OrderEntryDialog(QDialog):
    """Écran plein format : catalogue tactile à gauche, ardoise à droite."""

    def __init__(self, state, order_id: int, parent=None):
        super().__init__(parent)
        self.state = state
        self.order_id = int(order_id)
        self.order = OrderService.get(self.order_id)
        if self.order is None:
            raise ValueError("Commande introuvable.")
        self.currency = settings_service.get_currency()
        self.setWindowTitle(t('Commande — {label}').format(label=self._table_label()))
        self.setModal(True)
        fit_dialog_to_screen(
            self,
            min_width=900,
            min_height=560,
            preferred_width=1500,
            preferred_height=920,
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setSpacing(12)
        self.catalog = TouchCatalog(title=t('Produits'), show_barcode=True)
        self.catalog.product_activated.connect(self._add_product_by_id)
        self.catalog.barcode_scanned.connect(self._add_by_barcode)
        body.addWidget(self.catalog, 5)
        body.addWidget(self._build_ticket_panel(), 4)
        root.addLayout(body, 1)
        self.catalog.refresh()
        self._refresh()

    # --- Construction ------------------------------------------------------
    def _table_label(self) -> str:
        table = getattr(self.order, 'table', None)
        if table is not None:
            return table.display_name
        return t('Commande à emporter')

    def _build_header(self) -> QWidget:
        card = QFrame()
        card.setObjectName('Card')
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)
        self.header_label = QLabel('')
        self.header_label.setStyleSheet('font-size: 19px; font-weight: 800;')
        row.addWidget(self.header_label)
        row.addStretch(1)
        row.addWidget(QLabel(t('Client / N° :')))
        self.customer_input = QLineEdit(self.order.customer_name or '')
        self.customer_input.setPlaceholderText(t('Nom, surnom ou repère (ex. Chemise bleue)'))
        self.customer_input.setMinimumHeight(40)
        self.customer_input.setMinimumWidth(220)
        self.customer_input.editingFinished.connect(self._save_customer_name)
        row.addWidget(self.customer_input)
        transfer = QPushButton(t('Transférer'))
        transfer.setMinimumHeight(40)
        transfer.setToolTip(t('Déplacer cette commande sur une autre table.'))
        transfer.clicked.connect(self._transfer)
        row.addWidget(transfer)
        return card

    def _build_ticket_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName('Card')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title_row = QHBoxLayout()
        title = QLabel(t('Ardoise'))
        title.setObjectName('PageTitle')
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.count_label = QLabel('')
        self.count_label.setStyleSheet('color: #64748b;')
        title_row.addWidget(self.count_label)
        layout.addLayout(title_row)
        client_row = QHBoxLayout()
        client_row.addWidget(QLabel(t('pos.client')))
        self.client_search = ClientSearchField(
            placeholder=t('Tapez un nom ou un téléphone…')
        )
        client_row.addWidget(self.client_search, 1)
        layout.addLayout(client_row)
        self.ticket = TouchTicket(show_notes=True)
        self.ticket.quantity_changed.connect(self._on_quantity_changed)
        self.ticket.remove_requested.connect(self._on_remove)
        self.ticket.note_requested.connect(self._on_note)
        layout.addWidget(self.ticket, 1)
        discount_row = QHBoxLayout()
        discount_row.addWidget(QLabel(t('pos.discount')))
        self.discount_input = QDoubleSpinBox()
        self.discount_input.setRange(0, 0)
        self.discount_input.setDecimals(0)
        self.discount_input.setSingleStep(100)
        self.discount_input.setMinimumHeight(40)
        self.discount_input.valueChanged.connect(self._update_total)
        if not self.state.can(perms.APPLY_DISCOUNT):
            self.discount_input.setEnabled(False)
            self.discount_input.setToolTip(
                t("Vous n'avez pas l'autorisation d'appliquer une remise.")
            )
        discount_row.addWidget(self.discount_input, 1)
        layout.addLayout(discount_row)
        self.total_label = QLabel('')
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total_label.setStyleSheet('font-size: 26px; font-weight: 800;')
        layout.addWidget(self.total_label)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        kitchen = QPushButton(t('Bon cuisine'))
        kitchen.setMinimumHeight(46)
        kitchen.setToolTip(t('Imprime le bon de préparation (sans prix).'))
        kitchen.clicked.connect(self._print_kitchen)
        bill = QPushButton(t('Addition'))
        bill.setMinimumHeight(46)
        bill.setToolTip(t("Aperçu / impression de l'addition avant paiement."))
        bill.clicked.connect(self._show_bill)
        tools.addWidget(kitchen)
        tools.addWidget(bill)
        layout.addLayout(tools)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        close = QPushButton(t('Garder ouverte'))
        close.setMinimumHeight(56)
        close.setToolTip(t('Ferme cet écran : la commande reste ouverte sur la table.'))
        close.clicked.connect(self.accept)
        self.pay_button = QPushButton(t('Encaisser'))
        self.pay_button.setObjectName('Success')
        self.pay_button.setMinimumHeight(56)
        self.pay_button.clicked.connect(self._checkout)
        actions.addWidget(close, 1)
        actions.addWidget(self.pay_button, 2)
        layout.addLayout(actions)
        return panel

    # --- Données -----------------------------------------------------------
    def _reload_order(self) -> None:
        order = OrderService.get(self.order_id)
        if order is not None:
            self.order = order

    def _items(self) -> List:
        return list(self.order.items or [])

    def _subtotal(self) -> float:
        return round(sum(float(item.line_total or 0) for item in self._items()), 2)

    def _discount_ceiling(self) -> float:
        from app.services.cash_controls import max_discount_amount

        subtotal = self._subtotal()
        capped = max_discount_amount(subtotal, self.state.current_user)
        if capped is None:
            return max(0.0, subtotal)
        return max(0.0, min(subtotal, float(capped)))

    def _discount_value(self) -> float:
        return min(self._discount_ceiling(), float(self.discount_input.value()))

    def _total(self) -> float:
        return max(0.0, self._subtotal() - self._discount_value())

    def _refresh(self) -> None:
        self._reload_order()
        items = self._items()
        self.ticket.set_lines(
            [
                _ItemView(item, self.currency)
                for item in items
            ],
            self.currency,
        )
        count = sum(float(item.quantity or 0) for item in items)
        self.header_label.setText(
            f'{self._table_label()} · {self.order.public_id}'
        )
        self.count_label.setText(
            t('{count} article(s)').format(count=format_quantity(count))
        )
        self.catalog.set_stock_adjustments(OrderService.reserved_quantities())
        self._update_total()

    def _update_total(self) -> None:
        ceiling = self._discount_ceiling()
        self.discount_input.blockSignals(True)
        self.discount_input.setMaximum(ceiling)
        if float(self.discount_input.value()) > ceiling:
            self.discount_input.setValue(ceiling)
        self.discount_input.blockSignals(False)
        self.total_label.setText(
            t('Total : {amount}').format(
                amount=format_money(self._total(), self.currency)
            )
        )

    # --- Saisie ------------------------------------------------------------
    def _available_stock(self, product_id: int) -> float:
        product = ProductController.get(product_id)
        if product is None:
            return 0.0
        reserved = OrderService.reserved_quantities().get(int(product_id), 0.0)
        return float(product.quantity) - float(reserved)

    def _add_by_barcode(self, code: str) -> None:
        product = ProductController.find_by_barcode(code)
        if not product:
            warn(self, t('Aucun produit avec le code-barres « {code} ».').format(code=code))
            return
        self._add_product(product)

    def _add_product_by_id(self, product_id: int) -> None:
        product = ProductController.get(int(product_id))
        if product is not None:
            self._add_product(product)

    def _add_product(self, product) -> None:
        if getattr(product, 'free_amount_sale', False):
            self._add_free_amount(product)
            return
        price = float(product.sale_price or 0)
        min_price = float(product.min_price or 0)
        if min_price > 0 and price < min_price:
            warn(
                self,
                t(
                    "Impossible d'ajouter « {name} » : prix de vente {price} "
                    'inférieur au prix minimum {min_price}.'
                ).format(
                    name=product.name,
                    price=format_money(price, self.currency),
                    min_price=format_money(min_price, self.currency),
                ),
                t('Prix minimum'),
            )
            return
        available = self._available_stock(product.id)
        if available + 0.0001 < 1:
            warn(
                self,
                t('Stock insuffisant pour « {name} » : disponible {qty}.').format(
                    name=product.name, qty=format_quantity(available)
                ),
                t('Stock insuffisant'),
            )
            return
        try:
            OrderService.add_item(
                self.order_id,
                product_id=product.id,
                product_name=product.name,
                quantity=1,
                unit_price=price,
                purchase_price=float(product.purchase_price or 0),
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._refresh()

    def _add_free_amount(self, product) -> None:
        reference = float(product.sale_price or 0)
        if reference <= 0:
            warn(
                self,
                t(
                    '« {name} » : définissez un prix de vente de référence pour '
                    'la vente au montant libre.'
                ).format(name=product.name),
            )
            return
        available = self._available_stock(product.id)
        if available <= 0.0001:
            warn(
                self,
                t('Stock insuffisant pour « {name} » : disponible {qty}.').format(
                    name=product.name, qty=format_quantity(available)
                ),
                t('Stock insuffisant'),
            )
            return
        dialog = FreeAmountDialog(product.name, reference, parent=self)
        if not dialog.exec() or not dialog.amount:
            return
        amount = float(dialog.amount)
        estimated_qty = amount / reference
        pack = float(getattr(product, 'pack_content', 0) or 0)
        needed = round(estimated_qty / pack, 6) if pack > 0 else estimated_qty
        if needed > available + 0.0001:
            warn(
                self,
                t('Stock insuffisant pour « {name} » : disponible {qty}.').format(
                    name=product.name, qty=format_quantity(available)
                ),
                t('Stock insuffisant'),
            )
            return
        try:
            OrderService.add_item(
                self.order_id,
                product_id=product.id,
                product_name=(
                    f'{product.name} — {format_money(amount, self.currency)}'
                ),
                quantity=estimated_qty,
                unit_price=reference,
                purchase_price=float(product.cost_per_sale_unit),
                free_amount=True,
                amount=amount,
                merge=False,
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._refresh()

    def _item_at(self, row: int):
        items = self._items()
        if 0 <= row < len(items):
            return items[row]
        return None

    def _on_quantity_changed(self, row: int, quantity: float) -> None:
        item = self._item_at(row)
        if item is None:
            return
        if quantity <= 0:
            self._on_remove(row)
            return
        current = float(item.quantity or 0)
        if item.product_id and quantity > current:
            available = self._available_stock(item.product_id)
            if quantity - current > available + 0.0001:
                warn(
                    self,
                    t('Stock insuffisant pour « {name} » : disponible {qty}.').format(
                        name=item.product_name, qty=format_quantity(available)
                    ),
                    t('Stock insuffisant'),
                )
                return
        try:
            OrderService.set_item_quantity(self.order_id, item.id, quantity)
        except ValueError as exc:
            warn(self, str(exc))
        self._refresh()

    def _on_remove(self, row: int) -> None:
        item = self._item_at(row)
        if item is None:
            return
        if not confirm(
            self,
            t('Retirer « {name} » de la commande ?').format(name=item.product_name),
            t('Ardoise'),
        ):
            return
        try:
            OrderService.remove_item(self.order_id, item.id)
        except ValueError as exc:
            warn(self, str(exc))
        self._refresh()

    def _on_note(self, row: int) -> None:
        item = self._item_at(row)
        if item is None:
            return
        text, ok = QInputDialog.getText(
            self,
            t('Consigne cuisine / bar'),
            t('Consigne pour « {name} » (ex. sans piment, bien froid) :').format(
                name=item.product_name
            ),
            text=item.note or '',
        )
        if not ok:
            return
        try:
            OrderService.set_item_note(self.order_id, item.id, text)
        except ValueError as exc:
            warn(self, str(exc))
        self._refresh()

    def _save_customer_name(self) -> None:
        name = self.customer_input.text().strip()
        if name == (self.order.customer_name or '').strip():
            return
        try:
            OrderService.update_order(self.order_id, customer_name=name)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._reload_order()

    def _transfer(self) -> None:
        tables = [
            table
            for table in TableService.list()
            if table.id != getattr(self.order, 'table_id', None)
        ]
        if not tables:
            warn(self, t('Aucune autre table disponible.'))
            return
        labels = [f'{table.display_name} · {table.status}' for table in tables]
        choice, ok = QInputDialog.getItem(
            self, t('Transférer'), t('Nouvelle table :'), labels, 0, False
        )
        if not ok:
            return
        target = tables[labels.index(choice)]
        try:
            OrderService.transfer_to_table(self.order_id, target.id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._reload_order()
        self.setWindowTitle(t('Commande — {label}').format(label=self._table_label()))
        self._refresh()
        info(self, t('Commande transférée vers {name}.').format(name=target.display_name))

    # --- Impressions à la demande -----------------------------------------
    def _cashier_name(self) -> str:
        user = getattr(self.state, 'current_user', None)
        return getattr(user, 'username', '') or ''

    def _print_kitchen(self) -> None:
        from app.printers.order_receipt import print_order_kitchen

        if not self._items():
            warn(self, t('Aucun article à envoyer.'))
            return
        result = print_order_kitchen(self.order, cashier=self._cashier_name())
        if result.printed:
            info(self, result.message or t('Bon cuisine imprimé.'), t('Bon cuisine'))
        else:
            warn(
                self,
                t('Impression impossible.\n\n{message}\n\nFichier : {path}').format(
                    message=result.message, path=result.file_path
                ),
                t('Bon cuisine'),
            )

    def _show_bill(self) -> None:
        from app.printers.order_receipt import order_as_sale
        from app.ui.dialogs.ticket_dialog import TicketDialog

        if not self._items():
            warn(self, t('Aucun article sur cette commande.'))
            return
        TicketDialog(
            order_as_sale(self.order, cashier=self._cashier_name()),
            self,
            auto_print=False,
        ).exec()

    # --- Encaissement ------------------------------------------------------
    def _checkout(self) -> None:
        if not self._items():
            warn(self, t('Aucun article sur cette commande.'))
            return
        paid = checkout_order(
            self,
            self.state,
            self.order_id,
            discount=self._discount_value(),
            client_id=self.client_search.client_id,
        )
        if paid:
            self.accept()
        else:
            self._refresh()


class _ItemView:
    """Adapte une ligne de commande à l'affichage tactile."""

    def __init__(self, item, currency: str):
        self.name = item.product_name
        self.quantity = float(item.quantity or 0)
        self.unit_price = float(item.unit_price or 0)
        self.total = float(item.line_total or 0)
        self.free_amount = bool(item.free_amount)
        self.note = item.note or ''
        self.loyalty_reward = False
        self.currency = currency
