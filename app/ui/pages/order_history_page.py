"""Historique des commandes — Maquis Caisse PC."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.models.open_order import STATUS_OPEN
from app.services import settings_service
from app.services.order_service import OrderService
from app.utils.helpers import format_money


class OrderHistoryPage(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._on_open_order = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel(t("Historique commandes"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        layout.addWidget(
            QLabel(
                t(
                    "Commandes clôturées (payées ou annulées). Touchez une ligne pour le détail."
                )
            )
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("Rechercher ID, table, client…"))
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [t("N°"), t("Table"), t("Serveuse"), t("Total"), t("Statut"), t("Date")]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        open_btn = QPushButton(t("Ouvrir"))
        open_btn.clicked.connect(self._open_selected)
        refresh = QPushButton(t("Actualiser"))
        refresh.clicked.connect(self.refresh)
        row.addWidget(open_btn)
        row.addStretch()
        row.addWidget(refresh)
        layout.addLayout(row)
        self._ids: list[int] = []
        self.refresh()

    def set_order_opener(self, callback) -> None:
        self._on_open_order = callback

    def refresh(self) -> None:
        currency = settings_service.get_shop_info().currency or "FCFA"
        q = self.search.text().strip().lower()
        rows = OrderService.list_recent(limit=200)
        rows = [o for o in rows if o.status != STATUS_OPEN]
        if q:
            rows = [
                o
                for o in rows
                if q in (o.public_id or "").lower()
                or q in (o.customer_name or "").lower()
                or q in (getattr(o, "waitress_name", "") or "").lower()
            ]
        self._ids = [o.id for o in rows]
        self.table.setRowCount(len(rows))
        for i, o in enumerate(rows):
            table_name = "—"
            if getattr(o, "table", None) is not None:
                table_name = o.table.display_name
            waitress = getattr(o, "waitress_name", None) or "—"
            closed = ""
            if o.closed_at:
                closed = o.closed_at.strftime("%d/%m/%Y %H:%M")
            self.table.setItem(i, 0, QTableWidgetItem(o.public_id or str(o.id)))
            self.table.setItem(i, 1, QTableWidgetItem(table_name))
            self.table.setItem(i, 2, QTableWidgetItem(waitress))
            self.table.setItem(i, 3, QTableWidgetItem(format_money(float(o.total or 0), currency)))
            self.table.setItem(i, 4, QTableWidgetItem(o.status))
            self.table.setItem(i, 5, QTableWidgetItem(closed))

    def _open_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return
        if self._on_open_order:
            self._on_open_order(self._ids[row])
