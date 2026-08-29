"""Dialogue de confirmation d'annulation de vente avec motif obligatoire."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.ui.widgets.helpers import warn
from app.utils.cancel_reason import (
    MIN_CANCEL_REASON_LETTERS,
    count_letters,
    validate_cancel_reason,
)


class CancelSaleDialog(QDialog):
    """Demande un motif d'annulation (≥ 10 lettres) avant validation."""

    def __init__(self, ticket_number: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Annuler la vente")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.reason: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        info = QLabel(
            f"<b>Annuler la vente {ticket_number} ?</b><br/><br/>"
            "Les articles seront remis en stock et la vente ne comptera plus "
            "dans le chiffre d'affaires.<br/><br/>"
            "Un <b>motif obligatoire</b> (au moins 10 lettres) est requis."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addWidget(QLabel("Motif de l'annulation"))
        self.motif = QPlainTextEdit()
        self.motif.setPlaceholderText(
            "Ex. : erreur de saisie, client a changé d'avis, doublon…"
        )
        self.motif.setFixedHeight(100)
        layout.addWidget(self.motif)

        self.counter = QLabel(f"0 / {MIN_CANCEL_REASON_LETTERS} lettres minimum")
        self.counter.setStyleSheet("color: #b45309;")
        layout.addWidget(self.counter)
        self.motif.textChanged.connect(self._update_counter)

        buttons = QHBoxLayout()
        cancel = QPushButton("Retour")
        cancel.clicked.connect(self.reject)
        self.confirm = QPushButton("Valider l'annulation")
        self.confirm.setObjectName("Danger")
        self.confirm.clicked.connect(self._save)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm)
        layout.addLayout(buttons)
        self._update_counter()

    def _update_counter(self) -> None:
        n = count_letters(self.motif.toPlainText())
        ok = n >= MIN_CANCEL_REASON_LETTERS
        self.counter.setText(
            f"{n} / {MIN_CANCEL_REASON_LETTERS} lettres minimum"
            + (" — OK" if ok else "")
        )
        self.counter.setStyleSheet(
            "color: #16a34a;" if ok else "color: #b45309;"
        )

    def _save(self) -> None:
        reason = validate_cancel_reason(self.motif.toPlainText())
        if not reason:
            warn(
                self,
                "Indiquez un motif d'au moins 10 lettres "
                "(pas seulement des chiffres ou des signes).",
            )
            return
        self.reason = reason
        self.accept()
