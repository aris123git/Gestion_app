"""Dialogue après enregistrement commande — reste en caisse (app mobile)."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.i18n import t


class SavedOrderPromptDialog(QDialog):
    def __init__(self, public_id: str, print_enabled: bool, print_message: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Commande {id}").format(id=public_id))
        self.setModal(True)
        self.reprint_requested = False
        layout = QVBoxLayout(self)
        text = t("Commande enregistrée. Tu restes en Caisse.")
        if print_enabled:
            extra = ""
            if print_message:
                extra = f"\n\n{print_message}"
            text = (
                t("Commande enregistrée.")
                + extra
                + "\n\n"
                + t("Réimprime si besoin, ou OK pour continuer.")
            )
        layout.addWidget(QLabel(text))
        row = QHBoxLayout()
        ok = QPushButton("OK")
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        row.addStretch()
        if print_enabled:
            reprint = QPushButton(t("Réimprimer"))
            reprint.clicked.connect(self._reprint)
            row.addWidget(reprint)
        row.addWidget(ok)
        layout.addLayout(row)

    def _reprint(self) -> None:
        self.reprint_requested = True
        self.accept()
