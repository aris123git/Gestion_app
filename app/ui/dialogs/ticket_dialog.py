"""Aperçu et (ré)impression d'un ticket de caisse / facture demi-A4."""

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
from app.printers.half_a4_invoice import PAPER_HALF_A4, is_half_a4
from app.services import settings_service
from app.ui.widgets.helpers import info, warn


# (libellé UI, valeur stockée)
PAPER_CHOICES = (
    ("80 mm (thermique)", "80mm"),
    ("58 mm (thermique)", "58mm"),
    ("Demi-A4 (facture papier)", PAPER_HALF_A4),
)


class TicketDialog(QDialog):
    """Affiche le ticket en monospace et permet de l'imprimer / réimprimer."""

    def __init__(self, sale, parent=None, *, auto_print: bool | None = None):
        super().__init__(parent)
        self.sale = sale
        self.setWindowTitle(f"Ticket {sale.ticket_number}")
        self.setModal(True)
        self.setMinimumSize(480, 580)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(QLabel("Format :"))
        self.paper = QComboBox()
        for label, value in PAPER_CHOICES:
            self.paper.addItem(label, value)
        default = settings_service.get_setting("ticket_format", "80mm")
        index = self.paper.findData(default)
        if index < 0 and is_half_a4(default):
            index = self.paper.findData(PAPER_HALF_A4)
        self.paper.setCurrentIndex(index if index >= 0 else 0)
        self.paper.currentIndexChanged.connect(self._render)
        top.addWidget(self.paper)
        top.addStretch()
        layout.addLayout(top)

        self.format_hint = QLabel("")
        self.format_hint.setWordWrap(True)
        self.format_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(self.format_hint)

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
        self.print_button = QPushButton("Imprimer")
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

    def _paper_value(self) -> str:
        return self.paper.currentData() or "80mm"

    def _render(self) -> None:
        paper = self._paper_value()
        text = thermal_printer.render_ticket_text(self.sale, paper=paper)
        self.preview.setPlainText(text)
        if is_half_a4(paper):
            self.format_hint.setText(
                "Facture PDF sur demi-feuille A4 (210 × 148,5 mm) — "
                "utilisez une imprimante bureau avec du papier A4 coupé en deux."
            )
            self.print_button.setText("Imprimer la facture")
            self.setWindowTitle(f"Facture {self.sale.ticket_number}")
        else:
            self.format_hint.setText("Ticket thermique ESC/POS.")
            self.print_button.setText("Imprimer le ticket")
            self.setWindowTitle(f"Ticket {self.sale.ticket_number}")

    def _print(self) -> None:
        self.print_button.setEnabled(False)
        paper = self._paper_value()
        self.status.setText(
            "Génération / envoi de la facture…"
            if is_half_a4(paper)
            else "Envoi à l'imprimante…"
        )
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            result = thermal_printer.print_ticket(self.sale, paper=paper)
        finally:
            QApplication.restoreOverrideCursor()
            self.print_button.setEnabled(True)
            self.print_button.setText(
                "Réimprimer la facture" if is_half_a4(paper) else "Réimprimer le ticket"
            )

        if result.printed:
            self.status.setText(result.message)
            info(
                self,
                f"{result.message}\n\nFichier :\n{result.file_path}",
                "Impression",
            )
        else:
            self.status.setText(result.message)
            warn(
                self,
                f"Impression impossible.\n\n{result.message}\n\n"
                f"Fichier enregistré :\n{result.file_path}\n\n"
                "Astuce thermique : ne redémarrez pas le PC pour « forcer » "
                "l'impression — cela peut faire sortir tous les tickets d'un coup.\n"
                "Paramètres → Apparence & Ticket pour choisir l'imprimante "
                "ou vider la file d'attente.",
                "Impression impossible",
            )
