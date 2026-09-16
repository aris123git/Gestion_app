"""Saisie quantité (pavé) — comme QuantityOverlay sur tablette."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.i18n import t


class QuantityPadDialog(QDialog):
    def __init__(self, product_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(product_name)
        self.quantity = 1.0
        self._value = "1"
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{t('Quantité')} — {product_name}"))
        self.display = QLabel(self._value)
        self.display.setStyleSheet("font-size: 28px; font-weight: 700;")
        layout.addWidget(self.display)
        grid = QVBoxLayout()
        for row in ("789", "456", "123"):
            r = QHBoxLayout()
            for ch in row:
                b = QPushButton(ch)
                b.setMinimumSize(56, 48)
                b.clicked.connect(lambda _=False, d=ch: self._digit(d))
                r.addWidget(b)
            grid.addLayout(r)
        bottom = QHBoxLayout()
        clr = QPushButton("C")
        clr.clicked.connect(self._clear)
        zero = QPushButton("0")
        zero.clicked.connect(lambda: self._digit("0"))
        ok = QPushButton(t("OK"))
        ok.setObjectName("Primary")
        ok.clicked.connect(self._ok)
        bottom.addWidget(clr)
        bottom.addWidget(zero)
        bottom.addWidget(ok)
        grid.addLayout(bottom)
        layout.addLayout(grid)

    def _digit(self, d: str) -> None:
        if self._value == "0":
            self._value = d
        else:
            self._value += d
        self.display.setText(self._value)

    def _clear(self) -> None:
        self._value = "0"
        self.display.setText(self._value)

    def _ok(self) -> None:
        try:
            self.quantity = float(self._value.replace(",", "."))
        except ValueError:
            self.quantity = 0
        self.accept()
