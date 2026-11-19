"""Déverrouillage rapide sur un ordinateur où une connexion rapide a été activée."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout
from app.services import device_login
from app.ui.state import AppState
from app.ui.widgets.helpers import activate_and_center


class QuickLoginDialog(QDialog):
    """Propose directement le code rapide pour le compte mémorisé sur cet ordinateur."""

    def __init__(self, state: AppState, info: dict, parent=None):
        super().__init__(parent)
        self.state = state
        self.info = info
        self.use_password = False
        self.setWindowTitle(t('Connexion'))
        self.setModal(True)
        self.setFixedWidth(460)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 30, 30, 30)
        card = QFrame()
        card.setObjectName('Card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel(t('Connexion rapide'))
        title.setObjectName('PageTitle')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        who = QLabel(f"{t('Compte')} : <b>{info['username']}</b>")
        who.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code = QLineEdit()
        self.code.setPlaceholderText(t('Code rapide'))
        self.code.setEchoMode(QLineEdit.EchoMode.Password)
        self.code.returnPressed.connect(self._unlock)
        self.unlock_button = QPushButton(t('Déverrouiller'))
        self.unlock_button.setObjectName('Primary')
        self.unlock_button.clicked.connect(self._unlock)
        other = QPushButton(t("Utiliser un autre compte ou le mot de passe"))
        other.setFlat(True)
        other.setCursor(Qt.CursorShape.PointingHandCursor)
        other.setStyleSheet('QPushButton { border: none; color: #2563eb; background: transparent; font-size: 12px; }')
        other.clicked.connect(self._switch_to_password)
        layout.addWidget(title)
        layout.addWidget(who)
        layout.addSpacing(8)
        layout.addWidget(self.code)
        layout.addSpacing(6)
        layout.addWidget(self.unlock_button)
        layout.addWidget(other)
        outer.addWidget(card)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        activate_and_center(self)
        self.code.setFocus()

    def _switch_to_password(self) -> None:
        self.use_password = True
        self.reject()

    def _unlock(self) -> None:
        code = self.code.text()
        if not code:
            return
        blocked = device_login.seconds_blocked()
        if blocked:
            QMessageBox.warning(self, 'Connexion', f"Trop d'essais. Réessayez dans {blocked} secondes, ou utilisez le mot de passe.")
            return
        if not device_login.verify_code(code):
            QMessageBox.critical(self, 'Connexion', 'Code incorrect.')
            self.code.clear()
            self.code.setFocus()
            return
        user = self.state.auth.login_device(self.info['user_id'])
        if not user:
            QMessageBox.critical(self, 'Connexion', "Ce compte n'existe plus ou a été désactivé. Utilisez un autre compte.")
            device_login.clear_device_login()
            self.use_password = True
            self.reject()
            return
        self.accept()
