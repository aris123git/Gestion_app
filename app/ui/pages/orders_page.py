"""Commandes ouvertes — Maquis Caisse PC."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app.services import order_service, settings_service, table_service
from app.ui.dialogs.maquis_order_dialog import MaquisOrderDialog
from app.ui.widgets.helpers import confirm, info, warn
from app.utils.helpers import format_money

class OrdersPage(QWidget):

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel(t('Commandes ouvertes'))
        title.setObjectName('PageTitle')
        layout.addWidget(title)
        layout.addWidget(QLabel(t('Commandes en cours sur les tables. « Marquer payée » enregistre la vente sans impression.')))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([t('N°'), t('Table'), t('Client'), t('Total'), t('Statut')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._open_order)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        open_btn = QPushButton(t('Ouvrir la commande'))
        open_btn.setObjectName('Primary')
        open_btn.clicked.connect(self._open_order)
        actions.addWidget(open_btn)
        pay = QPushButton(t('Marquer payée (sans impression)'))
        pay.setObjectName('Success')
        pay.clicked.connect(self._pay)
        cancel = QPushButton(t('Annuler'))
        cancel.clicked.connect(self._cancel)
        refresh = QPushButton(t('Actualiser'))
        refresh.clicked.connect(self.refresh)
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

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _open_order(self) -> None:
        oid = self._selected_id()
        if not oid:
            warn(self, t('Sélectionnez une commande.'))
            return
        order = order_service.OrderService.get(oid)
        if not order:
            self.refresh()
            return
        table = None
        if order.table_id:
            table = next((item for item in table_service.TableService.list() if item.id == order.table_id), None)
        if table is None:
            warn(self, t('Commande sans table associée.'))
            return
        MaquisOrderDialog(table, order, state=self.state, parent=self).exec()
        self.refresh()

    def _pay(self) -> None:
        oid = self._selected_id()
        if not oid:
            warn(self, t('Sélectionnez une commande.'))
            return
        if not confirm(self, t('Marquer cette commande comme payée ?\n\nLa vente sera enregistrée (stock, rapports) sans impression.'), t('Commande')):
            return
        user = getattr(self.state, 'current_user', None)
        try:
            result = order_service.OrderService.settle(oid, user_id=getattr(user, 'id', None))
        except Exception as exc:
            warn(self, str(exc))
            return
        self.refresh()
        if hasattr(self.state, 'notify_data_changed'):
            self.state.notify_data_changed()
        currency = settings_service.get_shop_info().currency or 'FCFA'
        info(self, f'Commande payée — vente {result.ticket_number} enregistrée ({format_money(result.total, currency)}). Aucune impression.')

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
