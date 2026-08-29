"""Journal d'audit — accessible aux rôles disposant de VIEW_AUDIT."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services import audit_service, permissions as perms
from app.ui.state import AppState
from app.ui.widgets.helpers import page_title, warn
from app.utils.helpers import format_datetime


class AuditPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(page_title("Journal d'audit"))

        actions = QHBoxLayout()
        refresh = QPushButton("Actualiser")
        refresh.setObjectName("Primary")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        actions.addStretch()
        layout.addLayout(actions)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Utilisateur", "Action", "Détails"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        if not self.state.can(perms.VIEW_AUDIT):
            warn(self, "Vous n'avez pas l'autorisation de consulter l'audit.")
            return
        logs = audit_service.list_logs(limit=500)
        self.table.setRowCount(len(logs))
        for row, log in enumerate(logs):
            self.table.setItem(row, 0, QTableWidgetItem(format_datetime(log.date)))
            self.table.setItem(row, 1, QTableWidgetItem(log.username))
            self.table.setItem(row, 2, QTableWidgetItem(log.action))
            self.table.setItem(row, 3, QTableWidgetItem(log.details))
