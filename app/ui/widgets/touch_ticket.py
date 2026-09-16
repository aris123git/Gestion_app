"""Ardoise tactile (style tablette) : lignes larges, quantité par −/+ et pavé.

Partagée par la caisse et l'écran de commande des tables afin que l'affichage
des articles saisis soit identique dans les deux écrans de Maquis Caisse.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.utils.helpers import format_money, format_quantity


class TicketRow(QFrame):
    """Une ligne de l'ardoise : nom, note, prix unitaire, −/+ et total."""

    quantity_requested = Signal(int, float)
    keypad_requested = Signal(int)
    remove_requested = Signal(int)
    note_requested = Signal(int)
    selected = Signal(int)

    def __init__(self, row: int, line, currency: str, *, editable_qty: bool = True):
        super().__init__()
        self.row = row
        self.setObjectName("TicketRow")
        self.setStyleSheet(
            "#TicketRow { border: 1px solid #e2e8f0; border-radius: 10px;"
            " background: #ffffff; }"
        )
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(0, 1)
        quantity = float(getattr(line, "quantity", 0) or 0)
        unit_price = float(getattr(line, "unit_price", 0) or 0)
        loyalty = bool(getattr(line, "loyalty_reward", False))
        free_amount = bool(getattr(line, "free_amount", False))
        note = str(getattr(line, "note", "") or "").strip()
        label = str(getattr(line, "name", "") or "")
        if loyalty:
            label = f"{label} ({t('offert')})"
        name = QLabel(label)
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 16px; font-weight: 700; color: #0f172a;")
        grid.addWidget(name, 0, 0)
        details = [f"{format_money(unit_price, currency)} × {format_quantity(quantity)}"]
        if free_amount:
            details.append(t("montant libre"))
        if note:
            details.append(f"📝 {note}")
        detail = QLabel(" · ".join(details))
        detail.setWordWrap(True)
        detail.setStyleSheet("font-size: 12px; color: #64748b;")
        grid.addWidget(detail, 1, 0)
        controls = QHBoxLayout()
        controls.setSpacing(6)
        minus = self._round_button("−", "#f1f5f9", "#0f172a")
        minus.setEnabled(editable_qty and not free_amount)
        minus.clicked.connect(
            lambda: self.quantity_requested.emit(self.row, max(0.0, quantity - 1))
        )
        controls.addWidget(minus)
        qty_button = QPushButton(format_quantity(quantity))
        qty_button.setMinimumSize(64, 44)
        qty_button.setToolTip(t("Toucher pour saisir la quantité"))
        qty_button.setStyleSheet(
            "QPushButton { border: 1px solid #cbd5e1; border-radius: 8px;"
            " background: #ffffff; font-size: 17px; font-weight: 800; }"
        )
        qty_button.setEnabled(editable_qty and not free_amount)
        qty_button.clicked.connect(lambda: self.keypad_requested.emit(self.row))
        controls.addWidget(qty_button)
        plus = self._round_button("+", "#dbeafe", "#1d4ed8")
        plus.setEnabled(editable_qty and not free_amount)
        plus.clicked.connect(
            lambda: self.quantity_requested.emit(self.row, quantity + 1)
        )
        controls.addWidget(plus)
        grid.addLayout(controls, 0, 1, 2, 1)
        total_text = (
            t("OFFERT") if loyalty else format_money(float(line.total), currency)
        )
        total = QLabel(total_text)
        total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        total.setMinimumWidth(96)
        total.setStyleSheet("font-size: 17px; font-weight: 800; color: #0f172a;")
        grid.addWidget(total, 0, 2, 2, 1)
        actions = QVBoxLayout()
        actions.setSpacing(4)
        remove = self._round_button("✕", "#fee2e2", "#b91c1c")
        remove.setToolTip(t("Retirer la ligne"))
        remove.clicked.connect(lambda: self.remove_requested.emit(self.row))
        actions.addWidget(remove)
        note_btn = self._round_button("📝", "#f1f5f9", "#0f172a")
        note_btn.setToolTip(t("Consigne cuisine / bar"))
        note_btn.clicked.connect(lambda: self.note_requested.emit(self.row))
        self.note_button = note_btn
        actions.addWidget(note_btn)
        grid.addLayout(actions, 0, 3, 2, 1)

    @staticmethod
    def _round_button(text: str, background: str, colour: str) -> QPushButton:
        button = QPushButton(text)
        button.setFixedSize(44, 44)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            "QPushButton {"
            f" background: {background}; color: {colour}; border: none;"
            " border-radius: 10px; font-size: 18px; font-weight: 800;"
            "}"
            "QPushButton:disabled { color: #94a3b8; }"
        )
        return button

    def mousePressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        self.selected.emit(self.row)
        super().mousePressEvent(event)


class TouchTicket(QWidget):
    """Liste tactile des lignes saisies (panier de caisse ou ardoise de table)."""

    quantity_changed = Signal(int, float)
    remove_requested = Signal(int)
    note_requested = Signal(int)
    line_selected = Signal(int)

    def __init__(self, *, show_notes: bool = False, parent=None):
        super().__init__(parent)
        self._show_notes = show_notes
        self._rows: List[TicketRow] = []
        self._selected_row: Optional[int] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._host = QWidget()
        self._rows_layout = QVBoxLayout(self._host)
        self._rows_layout.setContentsMargins(2, 2, 2, 2)
        self._rows_layout.setSpacing(6)
        self._empty = QLabel(t("Aucun article. Touchez un produit à gauche."))
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #94a3b8; font-size: 15px; padding: 24px;")
        self._rows_layout.addWidget(self._empty)
        self._rows_layout.addStretch(1)
        self._scroll.setWidget(self._host)
        layout.addWidget(self._scroll, 1)

    def selected_row(self) -> Optional[int]:
        return self._selected_row

    def set_lines(self, lines: Sequence, currency: str, *, editable_qty: bool = True) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._empty:
                widget.deleteLater()
        self._rows = []
        if not lines:
            self._selected_row = None
            self._rows_layout.addWidget(self._empty)
            self._empty.show()
            self._rows_layout.addStretch(1)
            return
        self._empty.hide()
        for row, line in enumerate(lines):
            widget = TicketRow(row, line, currency, editable_qty=editable_qty)
            widget.note_button.setVisible(self._show_notes)
            widget.quantity_requested.connect(self.quantity_changed.emit)
            widget.keypad_requested.connect(self._open_keypad)
            widget.remove_requested.connect(self.remove_requested.emit)
            widget.note_requested.connect(self.note_requested.emit)
            widget.selected.connect(self._on_row_selected)
            self._rows_layout.addWidget(widget)
            self._rows.append(widget)
        self._rows_layout.addStretch(1)
        if self._selected_row is not None and self._selected_row >= len(self._rows):
            self._selected_row = None

    def _on_row_selected(self, row: int) -> None:
        self._selected_row = row
        self.line_selected.emit(row)

    def _open_keypad(self, row: int) -> None:
        from app.ui.dialogs.numpad_dialog import NumpadDialog

        if row >= len(self._rows):
            return
        dialog = NumpadDialog(
            title=t("Quantité"),
            parent=self,
        )
        if dialog.exec() and dialog.value is not None:
            self.quantity_changed.emit(row, float(dialog.value))
