"""Pavé numérique (saisie montants / quantités)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.i18n import t


class NumericKeypad(QWidget):
    """Chiffres 0-9, effacer, validation — comme NumericKeypad mobile."""

    value_changed = Signal(str)
    confirm_pressed = Signal()

    def __init__(
        self,
        *,
        confirm_label: str | None = None,
        max_digits: int = 12,
        parent=None,
    ):
        super().__init__(parent)
        self._max_digits = max_digits
        self._value = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel("")
        self._title.setStyleSheet("font-weight: 600; color: #64748b;")
        layout.addWidget(self._title)
        self.display = QLabel("0")
        self.display.setStyleSheet("font-size: 26px; font-weight: 700;")
        layout.addWidget(self.display)
        grid = QGridLayout()
        keys = [
            ("7", 0, 0),
            ("8", 0, 1),
            ("9", 0, 2),
            ("4", 1, 0),
            ("5", 1, 1),
            ("6", 1, 2),
            ("1", 2, 0),
            ("2", 2, 1),
            ("3", 2, 2),
            ("C", 3, 0),
            ("0", 3, 1),
            ("⌫", 3, 2),
        ]
        for label, row, col in keys:
            b = QPushButton(label)
            b.setMinimumHeight(48)
            if label == "C":
                b.clicked.connect(self.clear)
            elif label == "⌫":
                b.clicked.connect(self.backspace)
            else:
                b.clicked.connect(lambda _=False, d=label: self._digit(d))
            grid.addWidget(b, row, col)
        layout.addLayout(grid)
        row = QHBoxLayout()
        self.confirm_btn = QPushButton(confirm_label or t("Encaisser"))
        self.confirm_btn.setObjectName("Primary")
        self.confirm_btn.setMinimumHeight(52)
        self.confirm_btn.clicked.connect(self.confirm_pressed.emit)
        row.addWidget(self.confirm_btn)
        layout.addLayout(row)

    def set_title(self, text: str) -> None:
        self._title.setText(text)
        self._title.setVisible(bool(text))

    def set_confirm_enabled(self, enabled: bool) -> None:
        self.confirm_btn.setEnabled(enabled)

    def set_value(self, value: str) -> None:
        self._value = value or ""
        self.display.setText(self._value or "0")

    def value(self) -> str:
        return self._value

    def clear(self) -> None:
        self._value = ""
        self._refresh()

    def backspace(self) -> None:
        self._value = self._value[:-1]
        self._refresh()

    def _digit(self, d: str) -> None:
        if len(self._value) >= self._max_digits:
            return
        if self._value == "0" and d != "0":
            self._value = d
        elif self._value == "" and d == "0":
            self._value = "0"
        else:
            self._value = (self._value or "") + d
        self._refresh()

    def _refresh(self) -> None:
        self.display.setText(self._value or "0")
        self.value_changed.emit(self._value)
