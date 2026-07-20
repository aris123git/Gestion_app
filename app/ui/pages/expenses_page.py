"""Page de gestion des dépenses."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.controllers.expense_controller import ExpenseController
from app.services import audit_service, settings_service
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, make_card, page_title, warn
from app.utils.helpers import format_datetime, format_money


class ExpensesPage(QWidget):
    HEADERS = ["Date", "Catégorie", "Libellé", "Montant"]

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(page_title("Dépenses"))

        entry = QWidget()
        entry_layout = QHBoxLayout(entry)
        entry_layout.setContentsMargins(0, 0, 0, 0)
        self.category = QComboBox()
        self.category.addItems(config.EXPENSE_CATEGORIES)
        self.label = QLineEdit()
        self.label.setPlaceholderText("Libellé")
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000_000)
        self.amount.setDecimals(0)
        self.amount.setSingleStep(500)
        add = QPushButton("Enregistrer la dépense")
        add.setObjectName("Primary")
        add.clicked.connect(self._add)
        entry_layout.addWidget(self.category, 1)
        entry_layout.addWidget(self.label, 2)
        entry_layout.addWidget(self.amount, 1)
        entry_layout.addWidget(add)
        layout.addWidget(make_card(entry))

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        actions.addStretch()
        delete = QPushButton("Supprimer")
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete)
        actions.addWidget(delete)
        layout.addLayout(actions)

    def _add(self) -> None:
        if self.amount.value() <= 0:
            warn(self, "Le montant doit être supérieur à zéro.")
            return
        ExpenseController.create(
            {
                "category": self.category.currentText(),
                "label": self.label.text().strip(),
                "amount": self.amount.value(),
            },
            user_id=self.state.user_id,
        )
        audit_service.log_action(
            "Dépense", "Expense", f"{self.category.currentText()} {self.amount.value()}",
            self.state.user_id, getattr(self.state.current_user, "username", ""),
        )
        self.label.clear()
        self.amount.setValue(0)
        self.refresh()
        self.state.notify_data_changed()

    def _delete(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            warn(self, "Sélectionnez une dépense.")
            return
        if not self.state.is_admin:
            warn(self, "Seul un administrateur peut supprimer une dépense.")
            return
        if confirm(self, "Supprimer cette dépense ?"):
            ExpenseController.delete(self._ids[row])
            self.refresh()
            self.state.notify_data_changed()

    def refresh(self) -> None:
        expenses = ExpenseController.list()
        currency = settings_service.get_currency()
        self._ids = [e.id for e in expenses]
        self.table.setRowCount(len(expenses))
        for row, expense in enumerate(expenses):
            self.table.setItem(row, 0, QTableWidgetItem(format_datetime(expense.date)))
            self.table.setItem(row, 1, QTableWidgetItem(expense.category))
            self.table.setItem(row, 2, QTableWidgetItem(expense.label))
            self.table.setItem(row, 3, QTableWidgetItem(format_money(expense.amount, currency)))
