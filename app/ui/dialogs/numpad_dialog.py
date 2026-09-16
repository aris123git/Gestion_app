"""Pavé numérique tactile (quantités, montants) — écrans tablette / maquis."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.i18n import t
from app.utils.helpers import to_float


class NumpadDialog(QDialog):
    """Saisie au doigt d'un nombre positif (quantité, montant)."""

    def __init__(
        self,
        *,
        title: str = "",
        initial: str = "",
        suffix: str = "",
        allow_decimal: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.value: Optional[float] = None
        self._allow_decimal = allow_decimal
        self.setWindowTitle(title or t("Saisie"))
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        heading = QLabel(title or t("Saisie"))
        heading.setStyleSheet("font-size: 17px; font-weight: 700;")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        self.display = QLineEdit(str(initial or ""))
        self.display.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.display.setMinimumHeight(56)
        self.display.setStyleSheet("font-size: 26px; font-weight: 800;")
        if suffix:
            self.display.setPlaceholderText(suffix)
        layout.addWidget(self.display)
        grid = QGridLayout()
        grid.setSpacing(8)
        keys = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            ("0", 3, 0), ("00", 3, 1),
        ]
        for label, row, column in keys:
            grid.addWidget(self._key(label, lambda _=False, k=label: self._type(k)), row, column)
        if allow_decimal:
            grid.addWidget(self._key(",", lambda: self._type(".")), 3, 2)
        else:
            grid.addWidget(self._key("C", self._clear), 3, 2)
        layout.addLayout(grid)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        back = self._key("⌫", self._backspace)
        clear = self._key("C", self._clear)
        tools.addWidget(back)
        tools.addWidget(clear)
        layout.addLayout(tools)
        buttons = QHBoxLayout()
        cancel = QPushButton(t("common.cancel"))
        cancel.setMinimumHeight(48)
        cancel.clicked.connect(self.reject)
        validate = QPushButton(t("Valider"))
        validate.setObjectName("Success")
        validate.setMinimumHeight(48)
        validate.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(validate, 1)
        layout.addLayout(buttons)
        self.display.setFocus()

    @staticmethod
    def _key(label: str, handler) -> QPushButton:
        button = QPushButton(label)
        button.setMinimumSize(64, 56)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            "QPushButton { font-size: 20px; font-weight: 700; border: 1px solid #cbd5e1;"
            " border-radius: 10px; background: #f8fafc; }"
            "QPushButton:pressed { background: #dbeafe; }"
        )
        button.clicked.connect(handler)
        return button

    def _type(self, key: str) -> None:
        text = self.display.text()
        if key == "." and ("." in text or "," in text):
            return
        self.display.setText(f"{text}{key}")

    def _backspace(self) -> None:
        self.display.setText(self.display.text()[:-1])

    def _clear(self) -> None:
        self.display.clear()

    def _accept(self) -> None:
        value = to_float(self.display.text())
        if value < 0:
            return
        if not self._allow_decimal:
            value = float(int(value))
        self.value = value
        self.accept()
