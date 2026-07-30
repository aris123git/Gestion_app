"""Assistant de gestion — recommandations par règles métier."""

from __future__ import annotations

from PySide6.QtGui import QColor
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

from app.services.assistant_service import AssistantService
from app.ui.state import AppState
from app.ui.widgets.helpers import page_title


class AssistantPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(page_title("Assistant de gestion"))
        header.addStretch()
        refresh = QPushButton("Actualiser")
        refresh.setObjectName("Primary")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        layout.addLayout(header)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Niveau", "Recommandation", "Détail"])
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        rows = AssistantService.recommendations()
        self.table.setRowCount(len(rows))
        colors = {
            "danger": QColor("#fecaca"),
            "warning": QColor("#fde68a"),
            "info": QColor("#bfdbfe"),
        }
        for i, rec in enumerate(rows):
            level = QTableWidgetItem(rec.level)
            title = QTableWidgetItem(rec.title)
            detail = QTableWidgetItem(rec.detail)
            bg = colors.get(rec.level)
            if bg:
                for item in (level, title, detail):
                    item.setBackground(bg)
            self.table.setItem(i, 0, level)
            self.table.setItem(i, 1, title)
            self.table.setItem(i, 2, detail)
