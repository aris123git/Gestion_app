"""Aperçu / impression d'un reçu de règlement de dette.

Depuis la refonte Maquis Caisse : marquer une dette « Payé » n'imprime plus
automatiquement — le caissier voit l'aperçu et clique sur « Imprimer » s'il
veut vraiment un ticket papier. Cela évite le gaspillage de papier et les
tickets fantômes quand l'imprimante est éteinte / hors ligne.
"""
from __future__ import annotations
from app.i18n import t
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout
from app.printers.thermal_printer import print_debt_payment, render_debt_payment_text
from app.ui.widgets.helpers import info, warn

class DebtPaymentReceiptDialog(QDialog):
    """Affiche le reçu texte et propose (sans imposer) de l'imprimer."""

    def __init__(self, *, client_name: str, amount: float, payment_method: str, remaining_after: float, note: str='', cashier: str='', payment_id: int | None=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t('Reçu règlement dette'))
        self.setModal(True)
        self.resize(420, 480)
        self._kwargs = dict(client_name=client_name, amount=amount, payment_method=payment_method, remaining_after=remaining_after, note=note, cashier=cashier, payment_id=payment_id)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(QLabel(t("Règlement enregistré. Impression optionnelle.")))
        text = render_debt_payment_text(**self._kwargs)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(text)
        preview.setStyleSheet('font-family: monospace; font-size: 12px;')
        layout.addWidget(preview)
        buttons = QHBoxLayout()
        reprint = QPushButton(t('Imprimer'))
        reprint.setToolTip(t("Envoie le reçu vers l'imprimante par défaut. Rien n'est imprimé tant que vous ne cliquez pas ici."))
        reprint.clicked.connect(self._print)
        close = QPushButton(t('Fermer'))
        close.setObjectName('Primary')
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(reprint)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _print(self) -> None:
        result = print_debt_payment(**self._kwargs)
        if result.printed:
            info(self, result.message or 'Reçu imprimé.')
        else:
            warn(self, result.message or 'Impression impossible — copie enregistrée.')
