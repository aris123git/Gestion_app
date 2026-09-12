"""Commandes ouvertes — Maquis Caisse PC."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app.services import order_service, settings_service
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
        layout.addWidget(QLabel(t('Commandes en cours sur les tables. Encaissement via « Marquer payée ».')))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([t('N°'), t('Table'), t('Client'), t('Total'), t('Statut')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        pay = QPushButton(t('Marquer payée'))
        pay.setObjectName('Primary')
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

    def _pay(self) -> None:
        oid = self._selected_id()
        if not oid:
            warn(self, t('Sélectionnez une commande.'))
            return
        if not confirm(self, t('Marquer cette commande comme payée ?'), t('Commande')):
            return
        try:
            order_service.OrderService.mark_paid(oid)
            self.refresh()
            info(self, t("Commande payée — table libérée si plus d'autres commandes."))
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
