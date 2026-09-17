"""Saisie quantité (pavé tactile) — parité QuantityOverlay tablette."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.i18n import t


class QuantityPadDialog(QDialog):
    """Pavé 0–9 + décimale, grands boutons tactiles."""

    def __init__(self, product_name: str, parent=None, *, initial: float = 1.0):
        super().__init__(parent)
        self.setWindowTitle(product_name)
        self.setObjectName("MaquisQuantityPad")
        self.setModal(True)
        self.setMinimumSize(320, 420)
        self.quantity = float(initial) if initial > 0 else 1.0
        self._value = self._fmt(self.quantity)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        title = QLabel(product_name)
        title.setObjectName("SectionTitle")
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel(t("Quantité"))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #64748b;")
        layout.addWidget(hint)
        self.display = QLabel(self._value)
        self.display.setObjectName("MaquisPadDisplay")
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setMinimumHeight(64)
        layout.addWidget(self.display)
        grid = QGridLayout()
        grid.setSpacing(10)
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
            (".", 3, 0),
            ("0", 3, 1),
            ("C", 3, 2),
        ]
        for label, row, col in keys:
            btn = QPushButton(label)
            btn.setObjectName("MaquisPadKey")
            btn.setMinimumSize(72, 64)
            if label == "C":
                btn.clicked.connect(self._clear)
            elif label == ".":
                btn.clicked.connect(self._dot)
            else:
                btn.clicked.connect(lambda _=False, d=label: self._digit(d))
            grid.addWidget(btn, row, col)
        layout.addLayout(grid)
        actions = QHBoxLayout()
        cancel = QPushButton(t("common.cancel"))
        cancel.setMinimumHeight(48)
        cancel.clicked.connect(self.reject)
        ok = QPushButton(t("OK"))
        ok.setObjectName("Primary")
        ok.setMinimumHeight(48)
        ok.clicked.connect(self._ok)
        actions.addWidget(cancel)
        actions.addWidget(ok, 1)
        layout.addLayout(actions)

    @staticmethod
    def _fmt(value: float) -> str:
        if abs(value - int(value)) < 1e-9:
            return str(int(value))
        return f"{value:g}"

    def _digit(self, d: str) -> None:
        if self._value in ("0", ""):
            self._value = d
        else:
            self._value += d
        self.display.setText(self._value)

    def _dot(self) -> None:
        if "." in self._value or "," in self._value:
            return
        if not self._value:
            self._value = "0."
        else:
            self._value += "."
        self.display.setText(self._value)

    def _clear(self) -> None:
        self._value = "0"
        self.display.setText(self._value)

    def _ok(self) -> None:
        try:
            self.quantity = float(self._value.replace(",", "."))
        except ValueError:
            self.quantity = 0
        if self.quantity <= 0:
            self.quantity = 0
            return
        self.accept()
