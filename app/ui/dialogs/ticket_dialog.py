"""Aperçu et (ré)impression d'un ticket de caisse."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.printers import thermal_printer
from app.services import settings_service
from app.ui.widgets.helpers import info, warn


class TicketDialog(QDialog):
    """Affiche le ticket en monospace et permet de l'imprimer / réimprimer."""

    def __init__(self, sale, parent=None):
        super().__init__(parent)
        self.sale = sale
        self.setWindowTitle(f"Ticket {sale.ticket_number}")
        self.setModal(True)
        self.setMinimumSize(420, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(QLabel("Format :"))
        self.paper = QComboBox()
        self.paper.addItems(["80mm", "58mm"])
        default = settings_service.get_setting("ticket_format", "80mm")
        self.paper.setCurrentText(default if default in ("80mm", "58mm") else "80mm")
        self.paper.currentTextChanged.connect(self._render)
        top.addWidget(self.paper)
        top.addStretch()
        layout.addLayout(top)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Courier New", 10))
        layout.addWidget(self.preview)

        buttons = QHBoxLayout()
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        print_button = QPushButton("Imprimer le ticket")
        print_button.setObjectName("Primary")
        print_button.clicked.connect(self._print)
        buttons.addWidget(close)
        buttons.addStretch()
        buttons.addWidget(print_button)
        layout.addLayout(buttons)

        self._render()

    def _render(self) -> None:
        text = thermal_printer.render_ticket_text(self.sale, paper=self.paper.currentText())
        self.preview.setPlainText(text)

    def _print(self) -> None:
        result = thermal_printer.print_ticket(
            self.sale, paper=self.paper.currentText()
        )
        if result.printed:
            info(
                self,
                f"{result.message}\nCopie enregistrée :\n{result.file_path}",
                "Impression",
            )
        else:
            warn(
                self,
                f"Le ticket n'a pas pu être imprimé.\n{result.message}\n\n"
                f"Une copie a été enregistrée :\n{result.file_path}\n\n"
                "Configurez l'imprimante dans Paramètres → Apparence & Ticket.",
                "Impression impossible",
            )
