"""Propose d'activer la connexion rapide (code court, local à cet ordinateur)."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout
from app.services import device_login


class SetQuickCodeDialog(QDialog):
    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle(t('Connexion rapide'))
        self.setModal(True)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        message = QLabel(t("Choisissez un code court pour vous reconnecter plus vite sur cet ordinateur uniquement. "
                            "Votre mot de passe reste nécessaire sur tout autre poste, et vous pourrez désactiver ce code à tout moment dans Paramètres."))
        message.setWordWrap(True)
        layout.addWidget(message)
        form = QFormLayout()
        self.code = QLineEdit()
        self.code.setEchoMode(QLineEdit.EchoMode.Password)
        self.code.setPlaceholderText(t('Au moins 4 caractères'))
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(t('Code rapide'), self.code)
        form.addRow(t('Confirmation'), self.confirm)
        layout.addLayout(form)
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
