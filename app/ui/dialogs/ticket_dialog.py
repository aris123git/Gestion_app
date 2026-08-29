"""Aperçu, enregistrement et impression après encaissement.

Le caissier choisit ticket thermique 58/80 mm ou facture encre (demi-A4),
chacun vers l'imprimante configurée (thermique vs encre).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from app.printers import thermal_printer
from app.printers.half_a4_invoice import (
    PAPER_HALF_A4,
    build_invoice_pdf,
    is_half_a4,
)
from app.printers.printer_targets import describe_destinations, printer_for_paper
from app.services import settings_service
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import info, warn


class TicketDialog(QDialog):
    """Après encaissement : choix ticket thermique ou facture encre."""

    def __init__(self, sale, parent=None, *, auto_print: bool | None = None):
        super().__init__(parent)
        self.sale = sale
        self._saved_path: Path | None = None
        self.setWindowTitle(f"Impression — {sale.ticket_number}")
        self.setModal(True)
        fit_dialog_to_screen(
            self,
            min_width=360,
            min_height=320,
            preferred_width=520,
            preferred_height=640,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        thermal_name, invoice_name = describe_destinations()

        intro = QLabel(
            "<b>Choisissez comment imprimer</b><br/>"
            "Sélectionnez le ticket thermique (58/80 mm) ou la facture "
            "sur imprimante à encre."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.choice_group = QButtonGroup(self)
        self.radio_80 = QRadioButton(
            f"Ticket thermique 80 mm\n→ {thermal_name}"
        )
        self.radio_58 = QRadioButton(
            f"Ticket thermique 58 mm\n→ {thermal_name}"
        )
        self.radio_ink = QRadioButton(
            f"Facture papier (encre / laser, demi-A4)\n→ {invoice_name}"
        )
        for radio in (self.radio_80, self.radio_58, self.radio_ink):
            radio.setStyleSheet("QRadioButton { padding: 8px 4px; }")
            self.choice_group.addButton(radio)
            layout.addWidget(radio)

        default = settings_service.get_setting("ticket_format", "80mm")
        if is_half_a4(default):
            self.radio_ink.setChecked(True)
        elif default == "58mm":
            self.radio_58.setChecked(True)
        else:
            self.radio_80.setChecked(True)

        self.choice_group.buttonClicked.connect(self._on_format_changed)

        self.format_hint = QLabel("")
        self.format_hint.setWordWrap(True)
        self.format_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(self.format_hint)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        mono = QFont("DejaVu Sans Mono", 10)
        if not mono.exactMatch():
            mono = QFont("Courier New", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFixedPitch(True)
        self.preview.setFont(mono)
        self.preview.setStyleSheet(
            "QPlainTextEdit { line-height: 1; background: #ffffff; color: #111111; }"
        )
        layout.addWidget(self.preview)

        self.status = QLabel(
            "Enregistrez le ticket pour le conserver. L'impression est optionnelle."
        )
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        close = QPushButton("Fermer sans imprimer")
        close.clicked.connect(self.accept)
        self.print_button = QPushButton("Imprimer")
        self.print_button.setObjectName("Primary")
        self.print_button.clicked.connect(self._print)
        self.print_kitchen_button = QPushButton("Bon serveur")
        self.print_kitchen_button.setToolTip(
            "Imprime le bon serveur / cuisine (sans prix), selon le design choisi "
            "dans Paramètres → Designs des tickets."
        )
        self.print_kitchen_button.clicked.connect(self._print_kitchen)
        self.save_button = QPushButton("Enregistrer le ticket")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(close)
        buttons.addStretch()
        buttons.addWidget(self.print_kitchen_button)
        buttons.addWidget(self.print_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self._render()

        # Auto-impression uniquement pour le ticket thermique (pas la facture encre).
        if auto_print is None:
            auto_print = settings_service.get_setting("auto_print_ticket", "0") == "1"
        if auto_print and not is_half_a4(self._paper_value()):
            from PySide6.QtCore import QTimer

            QTimer.singleShot(50, self._print)

    def _paper_value(self) -> str:
        if self.radio_ink.isChecked():
            return PAPER_HALF_A4
        if self.radio_58.isChecked():
            return "58mm"
        return "80mm"

    def _on_format_changed(self) -> None:
        self._render()

    def _render(self) -> None:
        paper = self._paper_value()
        text = thermal_printer.render_ticket_text(self.sale, paper=paper)
        self.preview.setPlainText(text)
        target = printer_for_paper(paper) or "imprimante par défaut du système"
        if is_half_a4(paper):
            self.format_hint.setText(
                f"Facture demi-A4 (210 × 148,5 mm) vers « {target} ». "
                "Enregistrez le PDF, puis imprimez si besoin."
            )
            self.print_button.setText("Imprimer la facture (encre)")
            self.save_button.setText("Enregistrer la facture")
            self.print_kitchen_button.setVisible(False)
            self.setWindowTitle(f"Facture {self.sale.ticket_number}")
        else:
            from app.printers.ticket.options import is_kitchen_ticket_enabled
            from app.printers.ticket.registry import (
                get_design,
                resolve_client_design_id,
            )

            design = get_design(resolve_client_design_id())
            width = "58" if paper == "58mm" else "80"
            self.format_hint.setText(
                f"Ticket thermique {width} mm vers « {target} » — "
                f"design : {design.label}. "
                "Changez le modèle dans Paramètres → Designs des tickets."
            )
            self.print_button.setText(f"Imprimer le ticket {width} mm")
            self.save_button.setText("Enregistrer le ticket")
            self.print_kitchen_button.setVisible(is_kitchen_ticket_enabled())
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
        printer_name = printer_for_paper(paper)
        self.status.setText(
            "Envoi vers l'imprimante à encre…"
            if is_half_a4(paper)
            else "Envoi vers l'imprimante thermique…"
        )
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            result = thermal_printer.print_ticket(
                self.sale, paper=paper, printer_name=printer_name
            )
        finally:
            QApplication.restoreOverrideCursor()
            self.print_button.setEnabled(True)
            self._render()

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
                "Vérifiez Paramètres → Apparence du ticket :\n"
                "• Imprimante ticket (thermique)\n"
                "• Imprimante facture (encre)\n"
                "Astuce : « Enregistrer » conserve une copie ; "
                "imprimez quand l'imprimante est prête.",
                "Impression impossible",
            )

    def _print_kitchen(self) -> None:
        from app.printers.ticket.options import is_kitchen_ticket_enabled

        paper = self._paper_value()
        if is_half_a4(paper):
            return
        if not is_kitchen_ticket_enabled():
            warn(
                self,
                "Le bon serveur / cuisine est désactivé dans "
                "Paramètres → Designs des tickets.",
                "Bon serveur",
            )
            return
        self.print_kitchen_button.setEnabled(False)
        self.status.setText("Envoi du bon serveur / cuisine…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            result = thermal_printer.print_ticket(
                self.sale,
                paper=paper,
                printer_name=printer_for_paper(paper),
                role="kitchen",
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
