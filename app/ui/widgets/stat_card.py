"""Carte d'indicateur pour le tableau de bord."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class StatCard(QFrame):
    """Grande carte affichant un titre, une valeur et une couleur d'accent."""

    def __init__(self, title: str, value: str = "0", color: str = "#2563eb", icon: str = ""):
        super().__init__()
        self.setObjectName("StatCard")
        self.setMinimumHeight(120)
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

        layout.addWidget(header)
        layout.addWidget(self.value_label)
        layout.addStretch()

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)
