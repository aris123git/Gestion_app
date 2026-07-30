"""Dialogue d'historique des dettes et remboursements d'un client."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
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


class DebtHistoryDialog(QDialog):
    """Affiche les dettes et paiements d'un client."""

    def __init__(self, client_id: int, client_name: str, parent=None):
        super().__init__(parent)
        self.client_id = client_id
        self.setWindowTitle(f"Dettes — {client_name}")
        self.setModal(True)
        self.resize(820, 480)

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

        tabs = QTabWidget()
        tabs.addTab(self._build_debts_tab(), "Dettes")
        tabs.addTab(self._build_payments_tab(), "Remboursements")
        layout.addWidget(tabs)

        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)

        self._load()

    def _build_debts_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
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
        layout.addWidget(self.debts_table)
        return wrap

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

    def _load(self) -> None:
        currency = settings_service.get_currency()
        debts = DebtService.list_debts(client_id=self.client_id, limit=1000)
        self.debts_table.setRowCount(len(debts))
        for row, debt in enumerate(debts):
            ticket = ""
            if debt.sale is not None:
                ticket = getattr(debt.sale, "ticket_number", "") or str(debt.sale_id)
            due = debt.due_date.strftime("%d/%m/%Y") if debt.due_date else "—"
            status = STATUS_LABELS.get(debt.status, debt.status)
            if debt.is_overdue:
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
                self.debts_table.setItem(row, col, QTableWidgetItem(value))

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
