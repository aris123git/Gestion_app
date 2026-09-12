"""Fenêtre de connexion sécurisée."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout
from app.services.auth_service import AuthService
from app.ui.state import AppState
from app.ui.widgets.helpers import activate_and_center

class ChangePasswordDialog(QDialog):
    """Changement obligatoire du mot de passe admin par défaut."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle(t('Changer le mot de passe'))
        self.setModal(True)
        self.setFixedWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        message = QLabel(t('Le compte admin utilise encore le mot de passe par défaut. Choisissez un nouveau mot de passe pour continuer.'))
        message.setWordWrap(True)
        layout.addWidget(message)
        form = QFormLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(t('Minimum 6 caractères'))
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(t('Nouveau mot de passe'), self.password)
        form.addRow(t('Confirmation'), self.confirm)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        cancel = QPushButton(t('Annuler'))
        cancel.clicked.connect(self.reject)
        save = QPushButton(t('Enregistrer'))
        save.setObjectName('Primary')
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        password = self.password.text()
        if password != self.confirm.text():
            QMessageBox.warning(self, 'Mot de passe', 'Les deux mots de passe ne correspondent pas.')
            return
        try:
            AuthService.update_user(self.user.id, password=password)
        except ValueError as exc:
            QMessageBox.warning(self, 'Mot de passe', str(exc))
            return
        self.accept()

class LoginDialog(QDialog):
    """Demande les identifiants et ouvre la session via ``AuthService``."""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle(t('Connexion'))
        self.setModal(True)
        self.setFixedWidth(420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 30, 30, 30)
        outer.setSpacing(14)
        card = QFrame()
        card.setObjectName('Card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        from app.services import product_profile
        title = QLabel(product_profile.PARENT_NAME)
        title.setObjectName('PageTitle')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        product_line = QLabel(product_profile.product_label())
        product_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        product_line.setStyleSheet('font-weight: 600; color: #0f172a;')
        subtitle = QLabel(t('Veuillez vous connecter pour continuer'))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet('color: #64748b;')
        self.username = QLineEdit()
        self.username.setPlaceholderText(t("Nom d'utilisateur"))
        self.username.setMinimumHeight(38)
        self.username.returnPressed.connect(self._attempt_login)
        self.password = QLineEdit()
        self.password.setPlaceholderText(t('Mot de passe'))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self._attempt_login)
        self.show_password = QCheckBox('Afficher le mot de passe')
        self.show_password.toggled.connect(self._toggle_password)
        self.login_button = QPushButton(t('Se connecter'))
        self.login_button.setObjectName('Primary')
        self.login_button.clicked.connect(self._attempt_login)
        self.forgot_button = QPushButton(t('Mot de passe oublié ?'))
        self.forgot_button.setFlat(True)
        self.forgot_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forgot_button.setStyleSheet('QPushButton { border: none; color: #2563eb; background: transparent; }')
        self.forgot_button.clicked.connect(self._open_forgot_password)
        self.hint = QLabel(t('Astuce : compte par défaut admin / admin'))
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setStyleSheet('color: #94a3b8; font-size: 12px;')
        self.hint.setVisible(AuthService.default_admin_uses_default_password())
        layout.addWidget(title)
        layout.addWidget(product_line)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(QLabel(t('Utilisateur')))
        layout.addWidget(self.username)
        layout.addWidget(QLabel(t('Mot de passe')))
        layout.addWidget(self.password)
        layout.addWidget(self.show_password)
        layout.addSpacing(6)
        layout.addWidget(self.login_button)
        layout.addWidget(self.forgot_button)
        layout.addWidget(self.hint)
        outer.addWidget(card)

    def _selected_username(self) -> str:
        """Retourne l'identifiant saisi sans énumérer les comptes existants."""
        return self.username.text().strip()

    def _toggle_password(self, checked: bool) -> None:
        self.password.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)

    def _open_forgot_password(self) -> None:
        from app.ui.forgot_password_dialog import ForgotPasswordDialog
        dialog = ForgotPasswordDialog(self)
        if dialog.exec():
            self.hint.setVisible(AuthService.default_admin_uses_default_password())
            self.password.setFocus()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        activate_and_center(self)
        self.username.setFocus()

    def _attempt_login(self) -> None:
        username = self._selected_username()
        password = self.password.text()
        if not username or not password:
            QMessageBox.warning(self, 'Connexion', 'Veuillez remplir tous les champs.')
            return
        try:
            user = self.state.auth.login(username, password)
        except ValueError as exc:
            QMessageBox.critical(self, 'Connexion', str(exc))
            self.password.clear()
            self.password.setFocus()
            return
        if user:
            if user.username.lower() == 'admin' and AuthService.default_admin_uses_default_password():
                dialog = ChangePasswordDialog(user, self)
                if not dialog.exec():
                    self.state.auth.logout()
                    self.password.clear()
                    self.password.setFocus()
                    return
            self.accept()
        else:
            QMessageBox.critical(self, 'Connexion', 'Identifiants incorrects ou compte désactivé.')
            self.password.clear()
            self.password.setFocus()
