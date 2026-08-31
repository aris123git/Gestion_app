"""Carte d'indicateur pour le tableau de bord."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class StatCard(QFrame):
    """Grande carte affichant un titre, une valeur et une couleur d'accent."""

    def __init__(
        self,
        title: str,
        value: str = "0",
        color: str = "#2563eb",
        icon: str = "",
        *,
        hint: str = "",
        on_click: Optional[Callable[[], None]] = None,
    ):
        super().__init__()
        self.setObjectName("StatCard")
        self.setMinimumHeight(120)
        self._on_click = on_click
        self.setStyleSheet(
            f"#StatCard {{ background-color: {color}; border-radius: 14px; }}"
            "#StatCard QLabel { color: #ffffff; background: transparent; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        header = QLabel(f"{icon}  {title}".strip())
        header.setObjectName("StatTitle")

        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self.value_label.setStyleSheet("font-size: 26px; font-weight: 700;")

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("StatHint")
        self.hint_label.setStyleSheet("font-size: 12px; color: rgba(255,255,255,0.85);")
        self.hint_label.setVisible(bool(hint))

        layout.addWidget(header)
        layout.addWidget(self.value_label)
        layout.addWidget(self.hint_label)
        layout.addStretch()

        if on_click is not None:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.setToolTip("Cliquer pour voir le détail")

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_hint(self, hint: str) -> None:
        self.hint_label.setText(hint)
        self.hint_label.setVisible(bool(hint))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (
            self._on_click is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)
