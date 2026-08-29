"""Dialogue d'historique des dettes et remboursements d'un client."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.debt import STATUS_CANCELLED, STATUS_OPEN, STATUS_PAID, STATUS_PARTIAL
from app.services import settings_service
from app.services.debt_service import DebtService
from app.utils.helpers import format_datetime, format_money

STATUS_LABELS = {
    STATUS_OPEN: "En cours",
    STATUS_PARTIAL: "Partiellement payée",
    STATUS_PAID: "Soldée",
    STATUS_CANCELLED: "Annulée",
}

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
)


class DebtHistoryDialog(QDialog):
    """Affiche les dettes (par onglet) et paiements d'un client."""

    def __init__(self, client_id: int, client_name: str, parent=None):
        super().__init__(parent)
        self.client_id = client_id
        self.setWindowTitle(f"Dettes — {client_name}")
        self.setModal(True)
        self.resize(900, 520)
        self._debt_ids: List[int] = []
        self._selected_debt_id: Optional[int] = None
        self._current_sort = "recent"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        summary = DebtService.client_summary(client_id)
        currency = settings_service.get_currency()
        self.summary_label = QLabel(
            f"Solde : <b>{format_money(summary['total_remaining'], currency)}</b> — "
            f"{summary['active_count']} dette(s) active(s) — "
            f"{summary['overdue_count']} échéance(s) dépassée(s)"
        )
        layout.addWidget(self.summary_label)

        main_tabs = QTabWidget()
        debts_wrap = QWidget()
        debts_layout = QVBoxLayout(debts_wrap)
        debts_layout.setContentsMargins(0, 8, 0, 0)

        tools = QHBoxLayout()
        self.filter_tabs = QTabWidget()
        for label, _mode in DEBT_TABS:
            self.filter_tabs.addTab(QWidget(), label)
        self.filter_tabs.currentChanged.connect(self._reload_debts)
        debts_layout.addWidget(self.filter_tabs)

        tools.addWidget(QLabel("Trier :"))
        self.sort_combo = QComboBox()
        for label, value in SORT_CHOICES:
            self.sort_combo.addItem(label, value)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        tools.addWidget(self.sort_combo)
        tools.addStretch()
        debts_layout.addLayout(tools)

        self.debts_table = QTableWidget(0, 7)
        self.debts_table.setHorizontalHeaderLabels(
            [
                "Date",
                "Montant initial",
                "Reste",
                "Échéance",
                "Statut",
                "Vente",
                "Note",
            ]
        )
        self.debts_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.Stretch
        )
        self.debts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.debts_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.debts_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.debts_table.itemSelectionChanged.connect(self._remember_selection)
        debts_layout.addWidget(self.debts_table)

        main_tabs.addTab(debts_wrap, "Dettes")
        main_tabs.addTab(self._build_payments_tab(), "Remboursements")
        layout.addWidget(main_tabs)

        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)

        self._load_payments()
        self._reload_debts()

    def _build_payments_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        self.payments_table = QTableWidget(0, 5)
        self.payments_table.setHorizontalHeaderLabels(
            ["Date", "Montant", "Mode", "Dette #", "Note"]
        )
        self.payments_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.payments_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        layout.addWidget(self.payments_table)
        return wrap

    def _filter_mode(self) -> str:
        index = self.filter_tabs.currentIndex()
        if 0 <= index < len(DEBT_TABS):
            return DEBT_TABS[index][1]
        return "unpaid"

    def _on_sort_changed(self, _index: int = 0) -> None:
        new_sort = self.sort_combo.currentData() or "recent"
        if new_sort != self._current_sort:
            self._selected_debt_id = None
            self._current_sort = new_sort
            self.debts_table.clearSelection()
        self._reload_debts()

    def _remember_selection(self) -> None:
        row = self.debts_table.currentRow()
        if 0 <= row < len(self._debt_ids):
            self._selected_debt_id = self._debt_ids[row]

    def _reload_debts(self) -> None:
        currency = settings_service.get_currency()
        sort_by = self.sort_combo.currentData() or "recent"
        self._current_sort = sort_by
        debts = DebtService.list_debts(
            client_id=self.client_id,
            filter_mode=self._filter_mode(),
            sort_by=sort_by,
            limit=1000,
        )
        self._debt_ids = [int(d.id) for d in debts]
        self.debts_table.setRowCount(len(debts))
        for row, debt in enumerate(debts):
            ticket = ""
            if debt.sale is not None:
                ticket = getattr(debt.sale, "ticket_number", "") or str(debt.sale_id)
            due = debt.due_date.strftime("%d/%m/%Y") if debt.due_date else "—"
            status = STATUS_LABELS.get(debt.status, debt.status)
            overdue = bool(debt.is_overdue)
            if overdue:
                status += " (échue)"
            values = [
                format_datetime(debt.created_at) if debt.created_at else "—",
                format_money(debt.amount_initial, currency),
                format_money(debt.amount_remaining, currency),
                due,
                status,
                ticket or "—",
                debt.note or "—",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if overdue and col in (3, 4):
                    item.setForeground(QColor("#dc2626"))
                if col in (1, 2):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.debts_table.setItem(row, col, item)

        if self._selected_debt_id in self._debt_ids:
            row = self._debt_ids.index(self._selected_debt_id)
            self.debts_table.selectRow(row)
            self.debts_table.setCurrentCell(row, 0)
        else:
            self._selected_debt_id = None

    def _load_payments(self) -> None:
        currency = settings_service.get_currency()
        payments = DebtService.list_payments(client_id=self.client_id, limit=1000)
        self.payments_table.setRowCount(len(payments))
        for row, payment in enumerate(payments):
            values = [
                format_datetime(payment.payment_date),
                format_money(payment.amount, currency),
                payment.payment_method or "—",
                str(payment.debt_id),
                payment.note or "—",
            ]
            for col, value in enumerate(values):
                self.payments_table.setItem(row, col, QTableWidgetItem(value))
