"""WhatsApp à un fournisseur : commande (produits à réapprovisionner), relance, paiement, message libre."""
from __future__ import annotations

import re

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from app.i18n import t
from app.services import messaging_service as ms
from app.services import order_message, settings_service
from app.ui.widgets.helpers import warn


class SupplierMessageDialog(QDialog):
    def __init__(self, supplier_id: int, name: str, phone: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t('Écrire par WhatsApp'))
        self.setMinimumWidth(520)
        self.phone = phone
        shop = settings_service.get_shop_info().name or ''
        sign = f"\n{shop}" if shop else ''
        self.name = name
        self._lines = [(p.name, order_message.suggested_quantity(p), getattr(getattr(p, 'unit', None), 'name', '') or '', float(p.quantity or 0)) for p in order_message.products_to_order(supplier_id)]
        lines = [(n, q) for n, q, _u, _s in self._lines]
        many = len(lines) >= order_message.PDF_FROM
        self._templates = {
            'order': ((order_message.pdf_intro(len(lines), f"Bonjour {name}, voici ma commande") if many else order_message.format_order(lines, f"Bonjour {name}, je voudrais commander :")) + sign) if lines else '',
            'late': f"Bonjour {name}, où en est ma commande ? Merci de me tenir informé de la date de livraison.{sign}",
            'paid': f"Bonjour {name}, j'ai réglé [montant] pour la facture [n° facture]. Merci de confirmer la réception.{sign}",
            'free': '',
        }
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>{name}</b> · {phone or t('pas de numéro')}"))
        form = QFormLayout()
        self.model = QComboBox()
        self.model.addItem(t('Commande'), 'order')
        self.model.addItem(t('Relance de livraison'), 'late')
        self.model.addItem(t('Paiement effectué'), 'paid')
        self.model.addItem(t('Message libre'), 'free')
        self.model.currentIndexChanged.connect(self._apply_model)
        form.addRow(t('Modèle'), self.model)
        root.addLayout(form)
        self.hint = QLabel()
        self.hint.setStyleSheet('color: #64748b;')
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        self.attach = QCheckBox(t('Joindre la commande en PDF'))
        self.attach.setChecked(many)
        root.addWidget(self.attach)
        self.text = QPlainTextEdit()
        self.text.setMinimumHeight(220)
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
        self._apply_model()

    def _apply_model(self, *_a) -> None:
        key = self.model.currentData()
        text = self._templates.get(key, '')
        self.attach.setVisible(key == 'order' and bool(self._lines))
        if key == 'order' and not text:
            self.hint.setText(t("Aucun produit en rupture pour ce fournisseur (renseignez « Fournisseur habituel » sur les produits). Écrivez la commande à la main."))
        elif key == 'paid':
            self.hint.setText(t("Remplacez [montant] et [n° facture] avant d'envoyer."))
        else:
            self.hint.setText('')
        self.text.setPlainText(text)

    def _send(self) -> None:
        body = self.text.toPlainText().strip()
        if not body:
            warn(self, t('Écrivez un message.'))
            return
        if re.search(r'\[[^\]]+\]', body):
            warn(self, t('Remplacez les parties entre crochets [ ] avant d\'envoyer.'))
            return
        try:
            url = ms.whatsapp_link(self.phone, body)
        except ValueError:
            warn(self, t("Ce fournisseur n'a pas de numéro de téléphone valide."))
            return
        if self.model.currentData() == 'order' and self.attach.isChecked() and self._lines:
            from app.utils.helpers import format_quantity
            from app.ui.widgets.order_attach import send_with_pdf
            rows = [(n, u, format_quantity(s), format_quantity(q)) for n, q, u, s in self._lines]
            send_with_pdf(self, rows, self.name, url)
        else:
            QDesktopServices.openUrl(QUrl(url))
        self.accept()
