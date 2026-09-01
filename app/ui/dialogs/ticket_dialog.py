"""Aperçu, enregistrement et (ré)impression d'un ticket / facture demi-A4."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.printers import thermal_printer
from app.printers.half_a4_invoice import (
    PAPER_HALF_A4,
    build_invoice_pdf,
    is_half_a4,
)
from app.services import settings_service
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import info, warn


# (libellé UI, valeur stockée) — thermique d'abord = défaut caissier.
PAPER_CHOICES = (
    ("Ticket 80 mm", "80mm"),
    ("Ticket 58 mm", "58mm"),
    ("Facture papier", PAPER_HALF_A4),
)


class TicketDialog(QDialog):
    """Affiche le ticket et propose d'abord de l'enregistrer, puis d'imprimer."""

    def __init__(self, sale, parent=None, *, auto_print: bool | None = None):
        super().__init__(parent)
        self.sale = sale
        self._saved_path: Path | None = None
        self.setWindowTitle(f"Ticket {sale.ticket_number}")
        self.setModal(True)
        fit_dialog_to_screen(
            self,
            min_width=360,
            min_height=320,
            preferred_width=480,
            preferred_height=560,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(QLabel("Format :"))
        self.paper = QComboBox()
        for label, value in PAPER_CHOICES:
            self.paper.addItem(label, value)
        # Toujours partir du thermique (80/58) : la facture papier est un choix explicite.
        default = settings_service.get_setting("ticket_format", "80mm")
        if is_half_a4(default):
            default = "80mm"
        index = self.paper.findData(default if default in ("80mm", "58mm") else "80mm")
        self.paper.setCurrentIndex(index if index >= 0 else 0)
        self.paper.currentIndexChanged.connect(self._on_format_changed)
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

        self.status = QLabel(
            "Enregistrez le ticket pour le conserver. L'impression est optionnelle."
        )
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        self.print_button = QPushButton("Imprimer")
        self.print_button.clicked.connect(self._print)
        self.print_kitchen_button = QPushButton("Bon serveur")
        self.print_kitchen_button.setToolTip(
            "Imprime le bon serveur / cuisine (sans prix), selon le design choisi "
            "dans Paramètres → Designs des tickets."
        )
        self.print_kitchen_button.clicked.connect(self._print_kitchen)
        self.save_button = QPushButton("Enregistrer le ticket")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(close)
        buttons.addStretch()
        buttons.addWidget(self.print_kitchen_button)
        buttons.addWidget(self.print_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self._render()

        # Auto-impression désactivée par défaut : on demande d'enregistrer.
        # Conservé pour compatibilité si l'admin coche l'option dans Paramètres.
        if auto_print is None:
            auto_print = settings_service.get_setting("auto_print_ticket", "0") == "1"
        if auto_print and not is_half_a4(self._paper_value()):
            from PySide6.QtCore import QTimer

            QTimer.singleShot(50, self._print)

    def _paper_value(self) -> str:
        return self.paper.currentData() or "80mm"

    def _on_format_changed(self) -> None:
        self._render()

    def _render(self) -> None:
        paper = self._paper_value()
        text = thermal_printer.render_ticket_text(self.sale, paper=paper)
        self.preview.setPlainText(text)
        if is_half_a4(paper):
            self.format_hint.setText(
                "Facture sur papier A4 coupé en deux (210 × 148,5 mm). "
                "Enregistrez le PDF, puis imprimez si besoin."
            )
            self.print_button.setText("Imprimer la facture")
            self.save_button.setText("Enregistrer la facture")
            self.print_kitchen_button.setVisible(False)
            self.setWindowTitle(f"Facture {self.sale.ticket_number}")
        else:
            from app.printers.ticket.registry import (
                get_design,
                resolve_client_design_id,
            )

            design = get_design(resolve_client_design_id())
            self.format_hint.setText(
                f"Ticket thermique — design : {design.label}. "
                "Changez le modèle dans Paramètres → Designs des tickets."
            )
            self.print_button.setText("Imprimer le ticket")
            self.save_button.setText("Enregistrer le ticket")
            self.print_kitchen_button.setVisible(True)
            self.setWindowTitle(f"Ticket {self.sale.ticket_number}")

    def _default_save_path(self) -> Path:
        from app import config

        config.ensure_directories()
        paper = self._paper_value()
        if is_half_a4(paper):
            return config.TICKET_DIR / f"{self.sale.ticket_number}_demiA4.pdf"
        return config.TICKET_DIR / f"{self.sale.ticket_number}.txt"

    def _save(self) -> None:
        paper = self._paper_value()
        default = self._default_save_path()
        if is_half_a4(paper):
            filters = "PDF (*.pdf)"
            suggested = str(default)
        else:
            filters = "Texte (*.txt)"
            suggested = str(default)

        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer le ticket",
            suggested,
            filters,
        )
        if not path_str:
            self.status.setText("Enregistrement annulé.")
            return

        target = Path(path_str)
        self.save_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        saved: Path | None = None
        try:
            if is_half_a4(paper):
                if target.suffix.lower() != ".pdf":
                    target = target.with_suffix(".pdf")
                saved = build_invoice_pdf(self.sale, path=target)
            else:
                if target.suffix.lower() != ".txt":
                    target = target.with_suffix(".txt")
                content = thermal_printer.render_ticket_text(self.sale, paper=paper)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                saved = target
        except Exception as exc:
            self.status.setText(str(exc))
            warn(self, f"Impossible d'enregistrer le fichier.\n\n{exc}", "Enregistrement")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.save_button.setEnabled(True)

        if saved is None:
            return
        self._saved_path = saved
        self.status.setText(f"Enregistré : {saved}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Ticket enregistré")
        box.setText(f"Ticket enregistré :\n{saved}")
        open_btn = box.addButton("Ouvrir le dossier", QMessageBox.ButtonRole.ActionRole)
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(saved.parent)))

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
                "Astuce : utilisez « Enregistrer le ticket » pour conserver "
                "une copie, puis imprimez quand l'imprimante est prête.\n"
                "Paramètres → Designs des tickets pour changer le modèle.",
                "Impression impossible",
            )

    def _print_kitchen(self) -> None:
        paper = self._paper_value()
        if is_half_a4(paper):
            return
        self.print_kitchen_button.setEnabled(False)
        self.status.setText("Envoi du bon serveur / cuisine…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            result = thermal_printer.print_ticket(
                self.sale, paper=paper, role="kitchen"
            )
        finally:
            QApplication.restoreOverrideCursor()
            self.print_kitchen_button.setEnabled(True)

        if result.printed:
            self.status.setText(result.message)
            info(
                self,
                f"{result.message}\n\nFichier :\n{result.file_path}",
                "Bon serveur",
            )
        else:
            self.status.setText(result.message)
            warn(
                self,
                f"Impression impossible.\n\n{result.message}\n\n"
                f"Fichier :\n{result.file_path}",
                "Bon serveur",
            )
