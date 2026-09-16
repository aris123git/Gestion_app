"""Commandes en cours — Maquis Caisse PC."""

from __future__ import annotations

from app.i18n import t
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

from app.services import order_service, settings_service
from app.services.order_checkout_service import checkout_open_order
from app.services.order_status_labels import label_for_status
from app.ui.widgets.helpers import confirm, warn
from app.utils.helpers import format_money


class OrdersPage(QWidget):

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel(t("Commandes en cours"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        layout.addWidget(
            QLabel(
                t(
                    "Touche une commande pour le détail ou marquer comme payée (sans ticket client)."
                )
            )
        )
        self.summary = QLabel("")
        layout.addWidget(self.summary)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("Rechercher ID, serveuse, table…"))
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [t("N°"), t("Table"), t("Serveuse"), t("Total"), t("Reste"), t("Statut")]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        open_btn = QPushButton(t("Ouvrir"))
        open_btn.clicked.connect(self._open_selected)
        pay = QPushButton(t("Marquer payée"))
        pay.setObjectName("Primary")
        pay.clicked.connect(self._pay)
        cancel = QPushButton(t("Annuler"))
        cancel.clicked.connect(self._cancel)
        refresh = QPushButton(t("Actualiser"))
        refresh.clicked.connect(self.refresh)
        actions.addWidget(open_btn)
        actions.addWidget(pay)
        actions.addWidget(cancel)
        actions.addStretch()
        actions.addWidget(refresh)
        layout.addLayout(actions)
        self._ids: list[int] = []
        self._open_order_cb = None
        self.refresh()

    def set_order_opener(self, callback) -> None:
        self._open_order_cb = callback

    def refresh(self) -> None:
        currency = settings_service.get_shop_info().currency or "FCFA"
        rows = order_service.OrderService.list_open(limit=200)
        q = self.search.text().strip().lower()
        if q:
            filtered = []
            for o in rows:
                blob = " ".join(
                    [
                        o.public_id or "",
                        o.waitress_name or "",
                        o.table_label or "",
                        o.customer_name or "",
                    ]
                ).lower()
                if q in blob:
                    filtered.append(o)
            rows = filtered
        self._ids = [o.id for o in rows]
        self.table.setRowCount(len(rows))
        remaining_sum = 0.0
        for i, o in enumerate(rows):
            table_name = "—"
            if getattr(o, "table", None) is not None:
                table_name = o.table.display_name
            elif o.table_label:
                table_name = o.table_label
            rest = float(o.remaining_amount)
            remaining_sum += rest
            self.table.setItem(i, 0, QTableWidgetItem(o.public_id or str(o.id)))
            self.table.setItem(i, 1, QTableWidgetItem(table_name))
            self.table.setItem(i, 2, QTableWidgetItem(o.waitress_name or "—"))
            self.table.setItem(
                i, 3, QTableWidgetItem(format_money(float(o.total or 0), currency))
            )
            self.table.setItem(i, 4, QTableWidgetItem(format_money(rest, currency)))
            self.table.setItem(i, 5, QTableWidgetItem(label_for_status(o.status)))
        self.summary.setText(
            t("{n} ouvertes — Reste {amount}").format(
                n=len(rows),
                amount=format_money(remaining_sum, currency),
            )
        )

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _pay(self) -> None:
        oid = self._selected_id()
        if not oid:
            warn(self, t("Sélectionnez une commande."))
            return
        if checkout_open_order(oid, self.state, self):
            self.refresh()

    def _open_selected(self) -> None:
        oid = self._selected_id()
        if not oid:
            warn(self, t("Sélectionnez une commande."))
            return
        if self._open_order_cb:
            self._open_order_cb(oid)
        self.refresh()

    def _cancel(self) -> None:
        oid = self._selected_id()
        if not oid:
            warn(self, t("Sélectionnez une commande."))
            return
        if not confirm(self, t("Annuler cette commande ?"), t("Commande")):
            return
        try:
            order_service.OrderService.cancel(oid)
            self.refresh()
            self.state.notify_data_changed()
        except Exception as exc:
            warn(self, str(exc))
