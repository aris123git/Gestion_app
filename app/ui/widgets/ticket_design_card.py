"""Carte de sélection d'un design de ticket (aperçu + radio)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
)

from app.printers.ticket.renderer import render_ticket_preview


class TicketDesignCard(QFrame):
    """Carte cliquable affichant l'aperçu d'un design."""

    selected = Signal(str)

    def __init__(self, design_id: str, label: str, description: str = "", parent=None):
        super().__init__(parent)
        self.design_id = design_id
        self.setObjectName("TicketDesignCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel(label.upper())
        title.setStyleSheet("font-weight: 700; font-size: 13px;")
        layout.addWidget(title)

        if description:
            desc = QLabel(description)
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #64748b; font-size: 11px;")
            layout.addWidget(desc)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Courier New", 8))
        self.preview.setFixedHeight(160)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.preview)

        self.radio = QRadioButton("Sélectionner")
        self.radio.toggled.connect(self._on_toggled)
        layout.addWidget(self.radio)

        self._refresh_preview()
        self._apply_style(False)

    def _refresh_preview(self, paper: str = "80mm") -> None:
        try:
            text = render_ticket_preview(self.design_id, paper=paper)
        except Exception as exc:
            text = f"(aperçu indisponible)\n{exc}"
        self.preview.setPlainText(text)

    def _on_toggled(self, checked: bool) -> None:
        self._apply_style(checked)
        if checked:
            self.selected.emit(self.design_id)

    def set_checked(self, checked: bool) -> None:
        self.radio.blockSignals(True)
        self.radio.setChecked(checked)
        self.radio.blockSignals(False)
        self._apply_style(checked)

    def is_checked(self) -> bool:
        return self.radio.isChecked()

    def _apply_style(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                "#TicketDesignCard {"
                " border: 2px solid #2563eb;"
                " border-radius: 8px;"
                " background: #eff6ff;"
                "}"
            )
        else:
            self.setStyleSheet(
                "#TicketDesignCard {"
                " border: 1px solid #cbd5e1;"
                " border-radius: 8px;"
                " background: #ffffff;"
                "}"
            )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.radio.setChecked(True)
        super().mousePressEvent(event)
