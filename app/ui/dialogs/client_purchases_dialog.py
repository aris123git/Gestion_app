"""Historique des achats d'un client, avec réimpression du ticket / de la facture / du bon d'enlèvement."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.controllers.sale_controller import SaleController
from app.i18n import t
from app.services import audit_service, settings_service
from app.ui.widgets.helpers import warn
from app.utils.helpers import format_datetime, format_money


class ClientPurchasesDialog(QDialog):
    """Liste les ventes d'un client ; double-clic ou bouton = réimpression."""

    HEADERS = ['Date et heure', 'Ticket', 'Produits', 'Total', 'Statut']

    def __init__(self, client_id: int, client_name: str, state=None, parent=None):
        super().__init__(parent)
        self.client_id = client_id
        self.state = state
        self.setWindowTitle(f"{t('Achats')} — {client_name}")
        self.setModal(True)
        self.resize(980, 560)
        self._sale_ids: List[int] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        self.summary = QLabel('')
        self.summary.setStyleSheet('font-weight: 600;')
        layout.addWidget(self.summary)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('Filtrer : n° de ticket ou de facture, produit…'))
        self.search.setClearButtonEnabled(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._load)
        self.search.textChanged.connect(lambda _t: self._timer.start())
        layout.addWidget(self.search)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([t(h) for h in self.HEADERS])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._reprint)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        reprint = QPushButton(t('Réimprimer ticket / facture'))
        reprint.setObjectName('Primary')
        reprint.setToolTip(t("Ouvre la fenêtre d'impression de la vente sélectionnée (ticket, facture et bon d'enlèvement si activé)."))
        reprint.clicked.connect(self._reprint)
        close = QPushButton(t('Fermer'))
        close.clicked.connect(self.accept)
        actions.addWidget(reprint)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._load()

    def _load(self) -> None:
        currency = settings_service.get_currency()
        needle = self.search.text().strip().lower()
        sales = SaleController.list(client_id=self.client_id, with_items=True, limit=5000)
        rows = []
        for sale in sales:
            names = ', '.join(f'{i.product_name} ×{float(i.quantity):g}' for i in sale.items)
            if needle and needle not in names.lower() and needle not in (sale.ticket_number or '').lower() and needle not in (sale.invoice_number or '').lower():
                continue
            rows.append((sale, names))
        self._sale_ids = [s.id for s, _n in rows]
        self.table.setRowCount(len(rows))
        for r, (sale, names) in enumerate(rows):
            cancelled = sale.status == 'cancelled'
            values = [format_datetime(sale.date), sale.ticket_number, names, format_money(sale.total, currency),
                      t('Annulée') if cancelled else (t('Terminée') if sale.status == 'completed' else str(sale.status))]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(value))
        done = [s for s, _n in rows if s.status == 'completed']
        total = sum(float(s.total or 0) for s in done)
        self.summary.setText(f"{len(done)} {t('achat(s)')} — {t('total')} {format_money(total, currency)}")

    def _reprint(self, *_args) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._sale_ids):
            warn(self, t('Sélectionnez une vente.'))
            return
        sale = SaleController.get(self._sale_ids[row])
        if not sale:
            warn(self, t('Vente introuvable.'))
            return
        from app.ui.dialogs.ticket_dialog import TicketDialog

        TicketDialog(sale, self).exec()
        user = getattr(self.state, 'current_user', None)
        audit_service.log_action('Réimpression ticket', 'Sale', sale.ticket_number, getattr(self.state, 'user_id', None), getattr(user, 'username', ''))
