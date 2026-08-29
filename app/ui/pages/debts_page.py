"""Page Dettes clients : onglets Non payées / Payées / Échues / Tout."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.controllers.client_controller import ClientController
from app.models.debt import (
    STATUS_CANCELLED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_PARTIAL,
)
from app.services import permissions as perms, settings_service
from app.services.debt_service import DebtService
from app.ui.dialogs.debt_history_dialog import DebtHistoryDialog
from app.ui.dialogs.debt_payment_dialog import DebtPaymentDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import info, page_title, warn
from app.utils.helpers import format_datetime, format_money

STATUS_LABELS = {
    STATUS_OPEN: "En cours",
    STATUS_PARTIAL: "Partiellement payée",
    STATUS_PAID: "Soldée",
    STATUS_CANCELLED: "Annulée",
}

# (libellé onglet, filter_mode)
DEBT_TABS = (
    ("Non payées", "unpaid"),
    ("Payées", "paid"),
    ("Échues", "overdue"),
    ("Tout", "all"),
)

SORT_CHOICES = (
    ("Plus récentes", "recent"),
    ("Échéance", "due_date"),
    ("Montant restant", "remaining"),
    ("Client A → Z", "client"),
)


class DebtsPage(QWidget):
    """Registre des dettes avec filtres par onglet et tri persistant."""

    HEADERS = [
        "Date",
        "Client",
        "Téléphone",
        "Initial",
        "Reste",
        "Échéance",
        "Statut",
        "Vente",
        "Note",
    ]

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._debt_ids: List[int] = []
        self._selected_debt_id: Optional[int] = None
        self._current_sort = "recent"

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(page_title("Dettes clients"))
        header.addStretch()
        root.addLayout(header)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #64748b;")
        root.addWidget(self.summary)

        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (client, téléphone, note)…")
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _=None: self._search_timer.start())
        tools.addWidget(self.search, 3)

        tools.addWidget(QLabel("Trier :"))
        self.sort_combo = QComboBox()
        for label, value in SORT_CHOICES:
            self.sort_combo.addItem(label, value)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        tools.addWidget(self.sort_combo, 1)
        root.addLayout(tools)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        for label, _mode in DEBT_TABS:
            self.tabs.addTab(QWidget(), label)
        root.addWidget(self.tabs)

        # Une seule table partagée sous les onglets (contenu selon l'onglet actif).
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._remember_selection)
        self.table.doubleClicked.connect(self._open_history)
        root.addWidget(self.table)

        actions = QHBoxLayout()
        actions.addStretch()
        self.settle_btn = QPushButton("Régler")
        self.settle_btn.setObjectName("Success")
        self.settle_btn.clicked.connect(self._settle)
        self.history_btn = QPushButton("Historique client")
        self.history_btn.setObjectName("Primary")
        self.history_btn.clicked.connect(self._open_history)
        actions.addWidget(self.settle_btn)
        actions.addWidget(self.history_btn)
        root.addLayout(actions)

        # Place la table dans le premier onglet via layout dédié au refresh.
        self._tab_host = QVBoxLayout()
        # Les onglets QTabWidget portent des placeholders ; on affiche la table
        # juste en dessous pour rester simple et partageable.
        # (Les onglets ne servent qu'à choisir le filtre.)

    def _filter_mode(self) -> str:
        index = self.tabs.currentIndex()
        if 0 <= index < len(DEBT_TABS):
            return DEBT_TABS[index][1]
        return "unpaid"

    def _sort_by(self) -> str:
        return self.sort_combo.currentData() or "recent"

    def _on_tab_changed(self, _index: int = 0) -> None:
        # Changer d'onglet = autre liste : on garde la sélection si la dette
        # est encore visible, sinon elle sera effacée au rechargement.
        self.refresh()

    def _on_sort_changed(self, _index: int = 0) -> None:
        new_sort = self._sort_by()
        if new_sort != self._current_sort:
            # La sélection ne reste active que tant que le type de tri ne change pas.
            self._selected_debt_id = None
            self._current_sort = new_sort
            self.table.clearSelection()
        self.refresh()

    def _remember_selection(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._debt_ids):
            self._selected_debt_id = self._debt_ids[row]

    def _selected_debt_id_now(self) -> Optional[int]:
        row = self.table.currentRow()
        if 0 <= row < len(self._debt_ids):
            return self._debt_ids[row]
        return self._selected_debt_id

    def refresh(self) -> None:
        if not self.state.can(perms.MANAGE_CLIENT_DEBTS) and not self.state.can(
            perms.MANAGE_CLIENTS
        ):
            self.table.setRowCount(0)
            self._debt_ids = []
            self.summary.setText("Accès restreint aux dettes clients.")
            return

        mode = self._filter_mode()
        sort_by = self._sort_by()
        self._current_sort = sort_by
        debts = DebtService.list_debts(
            search=self.search.text().strip(),
            filter_mode=mode,
            sort_by=sort_by,
            limit=2000,
        )
        currency = settings_service.get_currency()
        self._debt_ids = [int(d.id) for d in debts]
        self.table.setRowCount(len(debts))

        total_remaining = 0.0
        for row, debt in enumerate(debts):
            client = debt.client
            client_name = client.name if client else "—"
            phone = (client.phone if client else "") or "—"
            due = debt.due_date.strftime("%d/%m/%Y") if debt.due_date else "—"
            status = STATUS_LABELS.get(debt.status, debt.status)
            overdue = bool(debt.is_overdue)
            if overdue:
                status += " · échue"
            ticket = "—"
            if debt.sale is not None:
                ticket = getattr(debt.sale, "ticket_number", "") or str(debt.sale_id)
            remaining = float(debt.amount_remaining or 0)
            total_remaining += remaining if debt.is_active else 0.0
            values = [
                format_datetime(debt.created_at) if debt.created_at else "—",
                client_name,
                phone,
                format_money(debt.amount_initial, currency),
                format_money(remaining, currency),
                due,
                status,
                ticket,
                debt.note or "—",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if overdue and col in (5, 6):
                    item.setForeground(QColor("#dc2626"))
                if col in (3, 4):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(row, col, item)

        labels = {
            "unpaid": "non payées",
            "paid": "payées / soldées",
            "overdue": "échues",
            "all": "au total",
        }
        self.summary.setText(
            f"{len(debts)} dette(s) {labels.get(mode, '')} — "
            f"reste dû affiché (actives) : "
            f"<b>{format_money(total_remaining, currency)}</b> — "
            f"tri : {self.sort_combo.currentText()}"
        )

        # Restaure la sélection précédente (même tri).
        if self._selected_debt_id in self._debt_ids:
            row = self._debt_ids.index(self._selected_debt_id)
            self.table.selectRow(row)
            self.table.setCurrentCell(row, 0)
        else:
            self._selected_debt_id = None

        can_settle = self.state.can(perms.MANAGE_CLIENT_DEBTS)
        self.settle_btn.setEnabled(can_settle)

    def _settle(self) -> None:
        if not self.state.can(perms.MANAGE_CLIENT_DEBTS):
            warn(self, "Vous n'avez pas l'autorisation de gérer les dettes client.")
            return
        debt_id = self._selected_debt_id_now()
        if not debt_id:
            warn(self, "Sélectionnez une dette.")
            return
        debt = DebtService.get(debt_id)
        if not debt or not debt.is_active or float(debt.amount_remaining or 0) <= 0:
            warn(self, "Cette dette n'a plus de reste dû.")
            return
        client = debt.client or ClientController.get(debt.client_id)
        name = client.name if client else f"Client #{debt.client_id}"
        dialog = DebtPaymentDialog(
            name, float(debt.amount_remaining), parent=self
        )
        if not dialog.exec() or not dialog.result_data:
            return
        try:
            DebtService.pay_debt(
                debt.id,
                dialog.result_data["amount"],
                payment_method=dialog.result_data["payment_method"],
                note=dialog.result_data["note"],
                user_id=self.state.user_id,
                username=getattr(self.state.current_user, "username", ""),
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        info(self, "Règlement enregistré.")
        self.refresh()
        self.state.notify_data_changed()

    def _open_history(self) -> None:
        debt_id = self._selected_debt_id_now()
        if not debt_id:
            warn(self, "Sélectionnez une dette.")
            return
        debt = DebtService.get(debt_id)
        if not debt:
            return
        client = debt.client or ClientController.get(debt.client_id)
        name = client.name if client else f"Client #{debt.client_id}"
        DebtHistoryDialog(debt.client_id, name, parent=self).exec()
        self.refresh()
