"""Aperçu / impression d'un reçu de règlement de dette."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.printers.thermal_printer import print_debt_payment, render_debt_payment_text
from app.ui.widgets.helpers import info, warn


class DebtPaymentReceiptDialog(QDialog):
    """Affiche le reçu texte et propose de (ré)imprimer."""

    def __init__(
        self,
        *,
        client_name: str,
        amount: float,
        payment_method: str,
        remaining_after: float,
        note: str = "",
        cashier: str = "",
        payment_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Reçu règlement dette")
        self.setModal(True)
        self.resize(420, 480)
        self._kwargs = dict(
            client_name=client_name,
            amount=amount,
            payment_method=payment_method,
            remaining_after=remaining_after,
            note=note,
            cashier=cashier,
            payment_id=payment_id,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(QLabel("Preuve d'encaissement — à remettre au client / conserver."))

        text = render_debt_payment_text(**self._kwargs)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(text)
        preview.setStyleSheet("font-family: monospace; font-size: 12px;")
        layout.addWidget(preview)

        buttons = QHBoxLayout()
        reprint = QPushButton("Imprimer")
        reprint.setObjectName("Primary")
        reprint.clicked.connect(self._print)
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(reprint)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        # Impression automatique à l'ouverture (copie toujours archivée).
        self._print(silent=True)

    def _print(self, silent: bool = False) -> None:
        result = print_debt_payment(**self._kwargs)
        if silent:
            return
        if result.printed:
            info(self, result.message or "Reçu imprimé.")
        else:
            warn(self, result.message or "Impression impossible — copie enregistrée.")
