"""Fenêtre de connexion sécurisée."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.services.auth_service import AuthService
from app.ui.state import AppState
from app.ui.widgets.helpers import activate_and_center


class LoginDialog(QDialog):
    """Demande les identifiants et ouvre la session via ``AuthService``."""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Connexion")
        self.setModal(True)
        self.setFixedWidth(420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 30, 30, 30)
        outer.setSpacing(14)

        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Gestion Commerciale")
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Veuillez vous connecter pour continuer")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #64748b;")

        # Sélection de l'utilisateur dans une liste déroulante.
        self.user_combo = QComboBox()
        self.user_combo.setEditable(True)  # Permet aussi de taper le nom.
        self._load_users()

        # Mot de passe avec possibilité d'afficher / masquer le code.
        self.password = QLineEdit()
        self.password.setPlaceholderText("Mot de passe")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self._attempt_login)

        self.show_password = QCheckBox("Afficher le mot de passe")
        self.show_password.toggled.connect(self._toggle_password)

        self.login_button = QPushButton("Se connecter")
        self.login_button.setObjectName("Primary")
        self.login_button.clicked.connect(self._attempt_login)

        self.hint = QLabel("Astuce : compte par défaut admin / admin")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setStyleSheet("color: #94a3b8; font-size: 12px;")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Utilisateur"))
        layout.addWidget(self.user_combo)
        layout.addWidget(QLabel("Mot de passe"))
        layout.addWidget(self.password)
        layout.addWidget(self.show_password)
        layout.addSpacing(6)
        layout.addWidget(self.login_button)
        layout.addWidget(self.hint)

        outer.addWidget(card)

    def _load_users(self) -> None:
        """Remplit la liste avec les comptes actifs (nom affiché + identifiant)."""
        self.user_combo.clear()
        try:
            users = [u for u in AuthService.list_users() if u.is_active]
        except Exception:
            users = []
        for user in users:
            display = user.full_name.strip() or user.username
            if user.full_name.strip():
                display = f"{user.full_name} ({user.username})"
            self.user_combo.addItem(display, user.username)
        if self.user_combo.count() == 0:
            self.user_combo.addItem("admin", "admin")

    def _selected_username(self) -> str:
        """Retourne l'identifiant sélectionné (data) ou le texte saisi."""
        data = self.user_combo.currentData()
        if data:
            return str(data)
        return self.user_combo.currentText().strip()

    def _toggle_password(self, checked: bool) -> None:
        self.password.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def showEvent(self, event) -> None:  # noqa: N802 - signature Qt
        super().showEvent(event)
        activate_and_center(self)
        self.password.setFocus()

    def _attempt_login(self) -> None:
        username = self._selected_username()
        password = self.password.text()
        if not username or not password:
            QMessageBox.warning(self, "Connexion", "Veuillez remplir tous les champs.")
            return
        user = self.state.auth.login(username, password)
        if user:
            self.accept()
        else:
            QMessageBox.critical(
                self, "Connexion", "Identifiants incorrects ou compte désactivé."
            )
            self.password.clear()
            self.password.setFocus()
