"""Commandes ouvertes — Maquis Caisse PC."""
from __future__ import annotations
from app import config
from app.controllers.product_controller import ProductController
from app.controllers.sale_controller import CartLine, SaleController
from app.i18n import t
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app.services import order_service, permissions as perms, settings_service
from app.ui.dialogs.maquis_order_dialog import MaquisOrderDialog
from app.ui.dialogs.payment_dialog import PaymentDialog
from app.ui.widgets.helpers import confirm, info, warn
from app.utils.helpers import format_money, format_quantity

class OrdersPage(QWidget):

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel(t('Commandes ouvertes'))
        title.setObjectName('PageTitle')
        layout.addWidget(title)
        layout.addWidget(QLabel(t('Même commande qu’à la tablette : produits, quantités, notes et total en temps réel.')))
        content = QHBoxLayout()
        content.setSpacing(12)
        list_panel = QFrame()
        list_panel.setObjectName('Card')
        list_layout = QVBoxLayout(list_panel)
        list_layout.addWidget(QLabel(t('Tables en cours')))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([t('N°'), t('Table'), t('Client'), t('Total'), t('Statut')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.doubleClicked.connect(self._edit)
        list_layout.addWidget(self.table, 1)
        content.addWidget(list_panel, 3)
        detail_panel = QFrame()
        detail_panel.setObjectName('Card')
        detail_layout = QVBoxLayout(detail_panel)
        self.detail_title = QLabel(t('Sélectionnez une commande'))
        self.detail_title.setObjectName('SectionTitle')
        detail_layout.addWidget(self.detail_title)
        self.detail_table = QTableWidget(0, 3)
        self.detail_table.setHorizontalHeaderLabels([t('Produit'), t('Qté'), t('Total')])
        self.detail_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.detail_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        detail_layout.addWidget(self.detail_table, 1)
        self.detail_note = QLabel('')
        self.detail_note.setWordWrap(True)
        self.detail_note.setStyleSheet('color:#64748b;')
        detail_layout.addWidget(self.detail_note)
        self.detail_total = QLabel('')
        self.detail_total.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.detail_total.setStyleSheet('font-size:22px;font-weight:800;')
        detail_layout.addWidget(self.detail_total)
        content.addWidget(detail_panel, 2)
        layout.addLayout(content, 1)
        actions = QHBoxLayout()
        edit = QPushButton(t('Modifier la commande'))
        edit.setObjectName('Primary')
        edit.clicked.connect(self._edit)
        pay = QPushButton(t('Marquer payée'))
        pay.setObjectName('Success')
        pay.clicked.connect(self._pay)
        cancel = QPushButton(t('Annuler'))
        cancel.clicked.connect(self._cancel)
        refresh = QPushButton(t('Actualiser'))
        refresh.clicked.connect(self.refresh)
        actions.addWidget(edit)
        actions.addWidget(pay)
        actions.addWidget(cancel)
        actions.addStretch()
        actions.addWidget(refresh)
        layout.addLayout(actions)
        self._ids: list[int] = []
        self.refresh()

    def refresh(self) -> None:
        currency = settings_service.get_shop_info().currency or 'FCFA'
        rows = order_service.OrderService.list_open(limit=100)
        self._ids = [o.id for o in rows]
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(rows))
        for i, o in enumerate(rows):
            table_name = '—'
            if getattr(o, 'table', None) is not None:
                table_name = o.table.display_name
            self.table.setItem(i, 0, QTableWidgetItem(o.public_id or str(o.id)))
            self.table.setItem(i, 1, QTableWidgetItem(table_name))
            self.table.setItem(i, 2, QTableWidgetItem(o.customer_name or '—'))
            self.table.setItem(i, 3, QTableWidgetItem(format_money(float(o.total or 0), currency)))
            self.table.setItem(i, 4, QTableWidgetItem(o.status))
        self.table.blockSignals(False)
        if rows:
            self.table.selectRow(0)
            # Une sélection survivante de QTableWidget peut ne pas réémettre le
            # signal après un repeuplement : synchroniser le détail explicitement.
            self._show_selected()
        else:
            self._clear_details()

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _clear_details(self) -> None:
        self.detail_title.setText(t('Aucune commande sélectionnée'))
        self.detail_table.setRowCount(0)
        self.detail_note.clear()
        self.detail_total.clear()

    def _show_selected(self) -> None:
        oid = self._selected_id()
        order = order_service.OrderService.get(oid) if oid else None
        if not order:
            self._clear_details()
            return
        table_name = order.table.display_name if order.table else t('Sans table')
        self.detail_title.setText(f'{order.public_id} · {table_name}')
        self.detail_table.setRowCount(len(order.items))
        for row, item in enumerate(order.items):
            self.detail_table.setItem(row, 0, QTableWidgetItem(item.product_name))
            qty = QTableWidgetItem(format_quantity(item.quantity))
            qty.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.detail_table.setItem(row, 1, qty)
            total = QTableWidgetItem(format_money(float(item.line_total), settings_service.get_currency()))
            total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.detail_table.setItem(row, 2, total)
        self.detail_note.setText(f'Note : {order.note}' if order.note else t('Aucune note'))
        self.detail_total.setText(f'Total : {format_money(float(order.total or 0), settings_service.get_currency())}')

    def _edit(self) -> None:
        oid = self._selected_id()
        if not oid:
            warn(self, t('Sélectionnez une commande.'))
            return
        dialog = MaquisOrderDialog(oid, self)
        dialog.order_changed.connect(self.refresh)
        dialog.order_changed.connect(self.state.notify_data_changed)
        dialog.exec()
        self.refresh()

    def _cashier_max_credit(self):
        from app.services.cash_controls import limits_for_user
        _, maximum = limits_for_user(self.state.current_user)
        return maximum

    def _pay(self) -> None:
        oid = self._selected_id()
        if not oid:
            warn(self, t('Sélectionnez une commande.'))
            return
        order = order_service.OrderService.get(oid)
        if not order:
            warn(self, t('Commande introuvable.'))
            return
        if not order.items:
            warn(self, t("Ajoutez au moins un produit avant d'encaisser."))
            return
        dialog = PaymentDialog(
            float(order.total or 0),
            allow_credit=self.state.can(perms.SELL_ON_CREDIT),
            max_credit=self._cashier_max_credit(),
            parent=self,
        )
        if not dialog.exec():
            return
        try:
            lines = []
            for item in order.items:
                product = ProductController.get(item.product_id) if item.product_id else None
                lines.append(CartLine(
                    product_id=item.product_id if product else None,
                    name=item.product_name,
                    unit_price=float(item.unit_price),
                    quantity=float(item.quantity),
                    purchase_price=float(product.purchase_price or 0) if product else 0,
                ))
            credit_requested = dialog.use_credit or any(
                payment.method == config.PAYMENT_METHOD_CREDIT
                for payment in dialog.result_payments
            )
            SaleController.create_sale(
                lines=lines,
                payments=dialog.result_payments,
                amount_received=dialog.amount_received,
                client_id=dialog.result_client_id,
                user_id=self.state.user_id,
                allow_credit=credit_requested,
                debt_due_date=dialog.credit_due_date,
            )
            order_service.OrderService.mark_paid(oid)
            self.refresh()
            self.state.notify_data_changed()
            # Intentionnel : pas de TicketDialog ni d'impression à cet endroit.
            info(self, t("Commande payée — table libérée. Aucun ticket imprimé."))
        except Exception as exc:
            warn(self, str(exc))

    def _cancel(self) -> None:
        oid = self._selected_id()
        if not oid:
            warn(self, t('Sélectionnez une commande.'))
            return
        if not confirm(self, t('Annuler cette commande ?'), t('Commande')):
            return
        try:
            order_service.OrderService.cancel(oid)
            self.refresh()
        except Exception as exc:
            warn(self, str(exc))
