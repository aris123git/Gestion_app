"""Propose d'activer la connexion rapide (code court, local à cet ordinateur)."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtWidgets import QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout
from app.services import device_login
from app.ui.widgets.helpers import dialog_header_banner


class SetQuickCodeDialog(QDialog):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle(t('Connexion rapide'))
        self.setModal(True)
        self.setMinimumWidth(420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(dialog_header_banner(t('Connexion rapide')))
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        outer.addLayout(layout, 1)
        message = QLabel(t("Choisissez un code court pour vous reconnecter plus vite sur cet ordinateur uniquement. "
                            "Votre mot de passe reste nécessaire sur tout autre poste, et vous pourrez désactiver ce code à tout moment dans Paramètres."))
        message.setWordWrap(True)
        message.setStyleSheet('color: #64748b;')
        layout.addWidget(message)
        card = QFrame()
        card.setObjectName('Card')
        form = QFormLayout(card)
        form.setContentsMargins(14, 14, 14, 14)
        self.code = QLineEdit()
        self.code.setEchoMode(QLineEdit.EchoMode.Password)
        self.code.setPlaceholderText(t('Au moins 4 caractères'))
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(t('Code rapide'), self.code)
        form.addRow(t('Confirmation'), self.confirm)
        layout.addWidget(card)
        buttons = QHBoxLayout()
        skip = QPushButton(t('Non merci'))
        skip.clicked.connect(self.reject)
        save = QPushButton(t('Activer'))
        save.setObjectName('Primary')
        save.clicked.connect(self._save)
        buttons.addWidget(skip)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        code = self.code.text()
        if code != self.confirm.text():
            QMessageBox.warning(self, 'Connexion rapide', 'Les deux codes ne correspondent pas.')
            return
        try:
            device_login.set_device_login(self.user.id, self.user.username, code)
        except ValueError as exc:
            QMessageBox.warning(self, 'Connexion rapide', str(exc))
            return
        self.accept()
