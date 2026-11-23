"""Dialogue après enregistrement commande — reste en caisse (app mobile)."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.i18n import t


class SavedOrderPromptDialog(QDialog):
    def __init__(self, public_id: str, print_enabled: bool, print_message: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Commande {id}").format(id=public_id))
        self.setModal(True)
        self.setMinimumWidth(380)
        self.reprint_requested = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header_banner = QFrame()
        header_banner.setObjectName("DialogHeaderBanner")
        header_banner.setStyleSheet("background-color: #16a34a;")
        header_layout = QVBoxLayout(header_banner)
        header_layout.setContentsMargins(20, 14, 20, 16)
        caption = QLabel(f"✓ {t('Commande')} {public_id}")
        caption.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 800;")
        header_layout.addWidget(caption)
        outer.addWidget(header_banner)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        outer.addLayout(layout, 1)

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
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
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
