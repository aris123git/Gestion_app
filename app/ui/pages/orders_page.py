"""Commandes ouvertes — Maquis Caisse PC.

Une commande encaissée devient une vraie vente : stock, bénéfices, tableau de
bord et dette client suivent le circuit normal de la caisse. Aucune impression
n'est déclenchée automatiquement (addition et bon cuisine restent à la demande).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.i18n import t
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services import permissions as perms, settings_service
from app.services.order_service import OrderService
from app.ui.pages.order_entry import OrderEntryDialog, checkout_order
from app.ui.widgets.helpers import confirm, info, page_title, warn
from app.utils.helpers import format_money, format_quantity


class OrdersPage(QWidget):
    """Liste des ardoises en cours avec ouverture, encaissement et annulation."""

    HEADERS = ('N°', 'Table', 'Client', 'Articles', 'Total', 'Ouverte depuis', 'Statut')

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(page_title(t('Commandes ouvertes')))
        header.addStretch(1)
        self.summary = QLabel('')
        self.summary.setStyleSheet('font-size: 15px; font-weight: 600;')
        header.addWidget(self.summary)
        layout.addLayout(header)
        layout.addWidget(
            QLabel(
                t(
                    'Ouvrez une ardoise pour saisir les produits, puis encaissez : '
                    'la vente est enregistrée (stock, tableau de bord) sans impression.'
                )
            )
        )
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([t(label) for label in self.HEADERS])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.doubleClicked.connect(self._open)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        open_btn = QPushButton(t('Ouvrir la commande'))
        open_btn.setObjectName('Primary')
        open_btn.setMinimumHeight(46)
        open_btn.clicked.connect(self._open)
        pay = QPushButton(t('Encaisser'))
        pay.setObjectName('Success')
        pay.setMinimumHeight(46)
        pay.setToolTip(t('Choix du mode de paiement (espèces, mobile, dette…).'))
        pay.clicked.connect(self._checkout)
        quick_pay = QPushButton(t('Marquer payée (espèces)'))
        quick_pay.setMinimumHeight(46)
        quick_pay.setToolTip(
            t('Encaisse la totalité en espèces, sans impression de ticket.')
        )
        quick_pay.clicked.connect(self._quick_pay)
        bill = QPushButton(t('Addition'))
        bill.setMinimumHeight(46)
        bill.clicked.connect(self._show_bill)
        cancel = QPushButton(t('Annuler la commande'))
        cancel.setObjectName('Danger')
        cancel.setMinimumHeight(46)
        cancel.clicked.connect(self._cancel)
        refresh = QPushButton(t('Actualiser'))
        refresh.setMinimumHeight(46)
        refresh.clicked.connect(self.refresh)
        actions.addWidget(open_btn)
        actions.addWidget(pay)
        actions.addWidget(quick_pay)
        actions.addWidget(bill)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(refresh)
        layout.addLayout(actions)
        self._ids: list[int] = []
        self.refresh()

    def refresh(self) -> None:
        currency = settings_service.get_currency()
        rows = OrderService.list_open(limit=200)
        self._ids = [o.id for o in rows]
        self.table.setRowCount(len(rows))
        total_open = 0.0
        for index, order in enumerate(rows):
            table_name = '—'
            if getattr(order, 'table', None) is not None:
                table_name = order.table.display_name
            items = sum(float(item.quantity or 0) for item in order.items)
            total = float(order.total or 0)
            total_open += total
            since = getattr(order, 'created_at', None)
            elapsed = '—'
            if since is not None:
                minutes = max(0, int((datetime.now() - since).total_seconds() // 60))
                elapsed = (
                    f'{minutes} min'
                    if minutes < 60
                    else f'{minutes // 60} h {minutes % 60:02d}'
                )
            values = (
                order.public_id or str(order.id),
                table_name,
                order.customer_name or '—',
                format_quantity(items),
                format_money(total, currency),
                elapsed,
                order.status,
            )
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        self.summary.setText(
            t('{count} ardoise(s) ouverte(s) — {amount}').format(
                count=len(rows), amount=format_money(total_open, currency)
            )
        )

    def _selected_id(self) -> Optional[int]:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _selected_order(self):
        order_id = self._selected_id()
        if not order_id:
            warn(self, t('Sélectionnez une commande.'))
            return None
        return OrderService.get(order_id)

    def _open(self) -> None:
        order_id = self._selected_id()
        if not order_id:
            warn(self, t('Sélectionnez une commande.'))
            return
        try:
            dialog = OrderEntryDialog(self.state, order_id, self)
        except ValueError as exc:
            warn(self, str(exc))
            return
        dialog.exec()
        self.refresh()
        self.state.notify_data_changed()

    def _checkout(self) -> None:
        """Encaissement avec choix des modes de paiement (comme en caisse)."""
        order_id = self._selected_id()
        if not order_id:
            warn(self, t('Sélectionnez une commande.'))
            return
        checkout_order(self, self.state, order_id)
        self.refresh()

    def _quick_pay(self) -> None:
        order = self._selected_order()
        if order is None:
            return
        currency = settings_service.get_currency()
        total = float(order.total or 0)
        if not confirm(
            self,
            t(
                'Encaisser {amount} en espèces pour {label} ?\n\n'
                "Aucun ticket n'est imprimé."
            ).format(
                amount=format_money(total, currency),
                label=order.public_id or str(order.id),
            ),
            t('Commande'),
        ):
            return
        try:
            OrderService.checkout(
                order.id,
                amount_received=total,
                user_id=self.state.user_id,
            )
        except Exception as exc:
            warn(self, str(exc))
            self.refresh()
            return
        self.refresh()
        self.state.notify_data_changed()
        info(self, t("Commande payée — table libérée si plus d'autres commandes."))

    def _show_bill(self) -> None:
        order = self._selected_order()
        if order is None:
            return
        if not order.items:
            warn(self, t('Aucun article sur cette commande.'))
            return
        from app.printers.order_receipt import order_as_sale
        from app.ui.dialogs.ticket_dialog import TicketDialog

        cashier = getattr(self.state.current_user, 'username', '') or ''
        TicketDialog(order_as_sale(order, cashier=cashier), self, auto_print=False).exec()

    def _cancel(self) -> None:
        order_id = self._selected_id()
        if not order_id:
            warn(self, t('Sélectionnez une commande.'))
            return
        if not self.state.can(perms.SELL):
            warn(self, t("Vous n'avez pas l'autorisation."))
            return
        if not confirm(self, t('Annuler cette commande ?'), t('Commande')):
            return
        try:
            OrderService.cancel(order_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        self.state.notify_data_changed()
