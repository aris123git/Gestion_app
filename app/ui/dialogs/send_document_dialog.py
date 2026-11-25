"""Envoyer un document PDF (facture, proforma, relevé) par WhatsApp ou par e-mail."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFormLayout, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QLabel, QVBoxLayout

from app.i18n import t
from app.services import messaging_service as ms
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import dialog_header_banner, info, warn


class SendDocumentDialog(QDialog):
    """WhatsApp ne permet pas de joindre un fichier automatiquement : la conversation s'ouvre avec le message prêt et le PDF
    s'ouvre à côté pour être joint. L'e-mail part avec le PDF en pièce jointe si l'envoi est configuré, sinon le logiciel
    de messagerie s'ouvre avec le message prêt."""

    def __init__(self, parent, pdf_path, phone: str = "", email: str = "", subject: str = "", message: str = "",
                 title: str = "Envoyer le document"):
        super().__init__(parent)
        self.pdf = Path(str(pdf_path))
        self.setWindowTitle(t(title))
        fit_dialog_to_screen(self, min_width=460, min_height=360, preferred_width=560, preferred_height=460)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(dialog_header_banner(t(title), t("Document : {name}").format(name=self.pdf.name)))
        v = QVBoxLayout()
        v.setContentsMargins(20, 16, 20, 20)
        outer.addLayout(v, 1)
        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        form.setContentsMargins(14, 14, 14, 14)
        self.phone = QLineEdit(phone)
        self.email = QLineEdit(email)
        self.subject = QLineEdit(subject)
        self.message = QPlainTextEdit(message)
        form.addRow(t("Téléphone WhatsApp"), self.phone)
        form.addRow(t("E-mail"), self.email)
        form.addRow(t("Objet"), self.subject)
        form.addRow(t("Message"), self.message)
        v.addWidget(card)
        row = QHBoxLayout()
        self.wa_button = QPushButton("WhatsApp")
        self.wa_button.setObjectName("Primary")
        self.wa_button.clicked.connect(self.send_whatsapp)
        self.mail_button = QPushButton(t("E-mail"))
        self.mail_button.clicked.connect(self.send_email)
        close = QPushButton(t("Fermer"))
        close.clicked.connect(self.reject)
        for b in (self.wa_button, self.mail_button, close):
            b.setAutoDefault(False)
            row.addWidget(b)
        v.addLayout(row)

    def _open_pdf(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.pdf)))

    def send_whatsapp(self) -> bool:
        try:
            link = ms.whatsapp_link(self.phone.text(), self.message.toPlainText())
        except ValueError as exc:
            warn(self, str(exc))
            return False
        QDesktopServices.openUrl(QUrl(link))
        self._open_pdf()
        info(self, t("WhatsApp s'ouvre avec le message prêt, et le PDF s'ouvre à côté : joignez-le dans la conversation (trombone), puis envoyez."))
        return True

    def send_email(self) -> bool:
        to = self.email.text().strip()
        if not ms.valid_email(to):
            warn(self, t("Adresse e-mail invalide."))
            return False
        if ms.email_configured():
            try:
                ms.smtp_send(to, self.subject.text(), self.message.toPlainText(), attachments=[self.pdf])
            except Exception as exc:
                warn(self, t("L'e-mail n'a pas pu être envoyé.\n\n{err}").format(err=exc))
                return False
            info(self, t("E-mail envoyé avec le PDF en pièce jointe."))
            return True
        QDesktopServices.openUrl(QUrl(f"mailto:{to}?subject={quote(self.subject.text())}&body={quote(self.message.toPlainText())}"))
        self._open_pdf()
        info(self, t("Votre messagerie s'ouvre avec le message prêt, et le PDF s'ouvre à côté : joignez-le puis envoyez. Pour un envoi automatique, configurez l'e-mail dans les messages groupés."))
        return True
