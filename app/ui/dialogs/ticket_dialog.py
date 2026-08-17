"""Aperçu et (ré)impression d'un ticket de caisse."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
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

    def __init__(self, sale, parent=None, *, auto_print: bool | None = None):
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

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        self.print_button = QPushButton("Imprimer le ticket")
        self.print_button.setObjectName("Primary")
        self.print_button.clicked.connect(self._print)
        buttons.addWidget(close)
        buttons.addStretch()
        buttons.addWidget(self.print_button)
        layout.addLayout(buttons)

        self._render()

        if auto_print is None:
            auto_print = settings_service.get_setting("auto_print_ticket", "1") == "1"
        if auto_print:
            # Laisse le dialogue s'afficher avant d'imprimer (feedback caissier).
            QTimer.singleShot(50, self._print)

    def _render(self) -> None:
        text = thermal_printer.render_ticket_text(self.sale, paper=self.paper.currentText())
        self.preview.setPlainText(text)

    def _print(self) -> None:
        self.print_button.setEnabled(False)
        self.status.setText("Envoi à l'imprimante…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            result = thermal_printer.print_ticket(
                self.sale, paper=self.paper.currentText()
            )
        finally:
            QApplication.restoreOverrideCursor()
            self.print_button.setEnabled(True)
            self.print_button.setText("Réimprimer le ticket")

        if result.printed:
            self.status.setText(result.message)
            info(
                self,
                f"{result.message}\n\nCopie enregistrée :\n{result.file_path}",
                "Impression",
            )
        else:
            self.status.setText(result.message)
            warn(
                self,
                f"Le ticket n'a pas pu être imprimé.\n\n{result.message}\n\n"
                f"Une copie a été enregistrée :\n{result.file_path}\n\n"
                "Astuce : ne redémarrez pas le PC pour « forcer » l'impression — "
                "cela peut faire sortir tous les tickets d'un coup. "
                "Allumez l'imprimante, puis cliquez sur « Réimprimer ».\n\n"
                "Paramètres → Apparence & Ticket pour choisir l'imprimante "
                "ou vider la file d'attente.",
                "Impression impossible",
            )
