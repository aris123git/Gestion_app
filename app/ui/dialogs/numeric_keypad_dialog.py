"""Pavé numérique tactile — quantité (aligné Maquis Caisse tablette)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.i18n import t
from app.ui.widgets.dialog_fit import fit_dialog_to_screen


class NumericKeypadDialog(QDialog):
    """Saisie quantité type tablette : première frappe remplace la valeur."""

    def __init__(
        self,
        *,
        title: str,
        subtitle: str = "",
        initial: str = "1",
        max_digits: int = 4,
        confirm_label: str = "OK",
        allow_delete_line: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        fit_dialog_to_screen(
            self, min_width=320, min_height=420, preferred_width=380, preferred_height=480
        )
        self.value: Optional[float] = None
        self.deleted = False
        self._text = (initial or "1").strip() or "1"
        self._max_digits = max(1, int(max_digits))
        self._replace_next = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        head = QLabel(title)
        head.setObjectName("PageTitle")
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.setWordWrap(True)
        layout.addWidget(head)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub.setStyleSheet("color: #64748b;")
            layout.addWidget(sub)

        self.display = QLabel(self._text)
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setStyleSheet(
            "font-size: 32px; font-weight: 800; color: #1d4ed8; "
            "background: #eff6ff; border-radius: 12px; padding: 14px;"
        )
        layout.addWidget(self.display)

        grid = QGridLayout()
        grid.setSpacing(8)
        keys = [
            ("1", 0, 0),
            ("2", 0, 1),
            ("3", 0, 2),
            ("4", 1, 0),
            ("5", 1, 1),
            ("6", 1, 2),
            ("7", 2, 0),
            ("8", 2, 1),
            ("9", 2, 2),
            ("C", 3, 0),
            ("0", 3, 1),
            ("⌫", 3, 2),
        ]
        for label, row, col in keys:
            btn = QPushButton(label)
            btn.setMinimumHeight(52)
            btn.setStyleSheet(
                "QPushButton { font-size: 20px; font-weight: 700; border-radius: 12px; }"
            )
            if label == "C":
                btn.clicked.connect(self._clear)
            elif label == "⌫":
                btn.clicked.connect(self._backspace)
            else:
                btn.clicked.connect(lambda _=False, d=label: self._digit(d))
            grid.addWidget(btn, row, col)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        cancel = QPushButton(t("Annuler"))
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        if allow_delete_line:
            delete = QPushButton(t("Supprimer"))
            delete.setObjectName("Danger")
            delete.clicked.connect(self._delete_line)
            actions.addWidget(delete)
        ok = QPushButton(confirm_label)
        ok.setObjectName("Primary")
        ok.setMinimumHeight(48)
        ok.clicked.connect(self._confirm)
        actions.addWidget(ok)
        layout.addLayout(actions)

    def _sync(self) -> None:
        self.display.setText(self._text or "0")

    def _digit(self, digit: str) -> None:
        if self._replace_next:
            self._text = digit if digit != "0" else "0"
            self._replace_next = False
        else:
            if len(self._text) >= self._max_digits:
                return
            if self._text == "0":
                self._text = digit
            else:
                self._text += digit
        self._sync()

    def _backspace(self) -> None:
        self._replace_next = False
        self._text = self._text[:-1]
        self._sync()

    def _clear(self) -> None:
        self._text = ""
        self._replace_next = True
        self._sync()

    def _delete_line(self) -> None:
        self.deleted = True
        self.value = None
        self.accept()

    def _confirm(self) -> None:
        raw = (self._text or "").strip()
        if not raw:
            return
        try:
            qty = float(raw.replace(",", "."))
        except ValueError:
            return
        if qty <= 0:
            return
        self.value = qty
        self.accept()


def ask_quantity(
    parent,
    *,
    product_name: str,
    unit_price_label: str,
    initial: float = 1,
    allow_delete_line: bool = False,
) -> tuple[Optional[float], bool]:
    """Retourne (quantité, deleted). (None, False) si annulé."""
    dialog = NumericKeypadDialog(
        title=product_name,
        subtitle=unit_price_label,
        initial=str(int(initial)) if float(initial).is_integer() else f"{initial:g}",
        allow_delete_line=allow_delete_line,
        parent=parent,
    )
    if not dialog.exec():
        return None, False
    if dialog.deleted:
        return None, True
    return dialog.value, False
