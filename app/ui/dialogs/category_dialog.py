"""Dialogue catégorie : nom + description (rayons / familles de produits)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.i18n import t
from app.ui.widgets.helpers import warn


class CategoryDialog(QDialog):
    def __init__(self, category=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            t("categories.edit") if category else t("categories.new")
        )
        self.setModal(True)
        self.setMinimumWidth(420)
        self.data: Optional[dict] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText(t("categories.name"))
        self.description = QTextEdit()
        self.description.setPlaceholderText(t("categories.description"))
        self.description.setMaximumHeight(100)
        form.addRow(t("categories.name") + " *", self.name)
        form.addRow(t("categories.description"), self.description)
        layout.addLayout(form)

        if category:
            self.name.setText(category.name or "")
            self.description.setPlainText(category.description or "")

        buttons = QHBoxLayout()
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self.reject)
        save = QPushButton(t("common.save"))
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        name = self.name.text().strip()
        if not name:
            warn(self, t("categories.name") + " *")
            return
        self.data = {
            "name": name,
            "description": self.description.toPlainText().strip(),
        }
        self.accept()
