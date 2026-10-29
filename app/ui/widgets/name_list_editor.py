"""Petit éditeur de liste de noms (ajout / retrait), enregistré tout de suite."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget

from app.i18n import t
from app.services import transport_service


class NameListEditor(QWidget):
    def __init__(self, kind: str, title: str, placeholder: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(f'<b>{title}</b>'))
        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.returnPressed.connect(self._add)
        add = QPushButton(t('Ajouter'))
        add.clicked.connect(self._add)
        remove = QPushButton(t('Retirer'))
        remove.clicked.connect(self._remove)
        row.addWidget(self.input, 1)
        row.addWidget(add)
        row.addWidget(remove)
        layout.addLayout(row)
        self.reload()

    def reload(self) -> None:
        self.list.clear()
        self.list.addItems(transport_service.list_names(self.kind))

    def _add(self) -> None:
        if self.input.text().strip():
            transport_service.add(self.kind, self.input.text())
            self.input.clear()
            self.reload()

    def _remove(self) -> None:
        item = self.list.currentItem()
        if item:
            transport_service.remove(self.kind, item.text())
            self.reload()
