"""Message WhatsApp à un seul client : modèle au choix, texte modifiable, puis ouverture de WhatsApp."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from app.i18n import t
from app.services import messaging_service as ms
from app.services import settings_service
from app.ui.widgets.helpers import warn
from app.utils.helpers import format_money


class ClientMessageDialog(QDialog):
    def __init__(self, name: str, phone: str, debt: float = 0.0, no_marketing: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t('Écrire par WhatsApp'))
        self.setMinimumWidth(480)
        self.phone = phone
        shop = settings_service.get_shop_info().name or ''
        cur = settings_service.get_currency()
        self._templates = {
            'free': '',
            'debt': f"Bonjour {name}, ceci est un rappel : vous avez un solde de {format_money(debt, cur)} chez {shop}. Merci de passer le régler quand vous pouvez.".replace(' chez .', '.'),
        }
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>{name}</b> · {phone or t('pas de numéro')}"))
        if no_marketing:
            note = QLabel(t("Ce client a demandé à ne plus recevoir de messages promotionnels."))
            note.setStyleSheet('color: #b45309;')
            root.addWidget(note)
        form = QFormLayout()
        self.model = QComboBox()
        self.model.addItem(t('Message libre'), 'free')
        if debt > 0:
            self.model.addItem(t('Rappel de dette'), 'debt')
        self.model.currentIndexChanged.connect(self._apply_model)
        form.addRow(t('Modèle'), self.model)
        root.addLayout(form)
        self.text = QPlainTextEdit()
        self.text.setMinimumHeight(120)
        root.addWidget(self.text)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton(t('Annuler'))
        cancel.clicked.connect(self.reject)
        self.send_button = QPushButton(t('Envoyer sur WhatsApp'))
        self.send_button.setObjectName('Success')
        self.send_button.clicked.connect(self._send)
        row.addWidget(cancel)
        row.addWidget(self.send_button)
        root.addLayout(row)
        if debt > 0:
            self.model.setCurrentIndex(self.model.findData('debt'))
        self._apply_model()

    def _apply_model(self, *_a) -> None:
        self.text.setPlainText(self._templates.get(self.model.currentData(), ''))

    def _send(self) -> None:
        body = self.text.toPlainText().strip()
        if not body:
            warn(self, t('Écrivez un message.'))
            return
        try:
            url = ms.whatsapp_link(self.phone, body)
        except ValueError:
            warn(self, t("Ce client n'a pas de numéro de téléphone valide."))
            return
        QDesktopServices.openUrl(QUrl(url))
        self.accept()
