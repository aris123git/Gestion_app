"""Fenêtre de connexion sécurisée."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

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

        self.username = QLineEdit()
        self.username.setPlaceholderText("Nom d'utilisateur")
        self.username.setText("admin")

        self.password = QLineEdit()
        self.password.setPlaceholderText("Mot de passe")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self._attempt_login)

        self.login_button = QPushButton("Se connecter")
        self.login_button.setObjectName("Primary")
        self.login_button.clicked.connect(self._attempt_login)

        self.hint = QLabel("Astuce : compte par défaut admin / admin")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setStyleSheet("color: #94a3b8; font-size: 12px;")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Nom d'utilisateur"))
        layout.addWidget(self.username)
        layout.addWidget(QLabel("Mot de passe"))
        layout.addWidget(self.password)
        layout.addSpacing(6)
        layout.addWidget(self.login_button)
        layout.addWidget(self.hint)

        outer.addWidget(card)

    def showEvent(self, event) -> None:  # noqa: N802 - signature Qt
        super().showEvent(event)
        activate_and_center(self)
        self.password.setFocus()

    def _attempt_login(self) -> None:
        username = self.username.text().strip()
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
