"""Dialogue d'autorisation : mot de passe administrateur pour actions sensibles."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.services.auth_service import AuthService
from app.ui.widgets.helpers import warn


class AuthorizeDialog(QDialog):
    """Demande les identifiants d'un administrateur pour lever une restriction.

    Utilisé par exemple lorsqu'un gestionnaire annule une vente, ou pour toute
    opération sensible nécessitant la validation d'un responsable.
    """

    def __init__(self, reason: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Autorisation requise")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.authorized_username: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        intro = QLabel(
            reason
            or "Cette action nécessite l'autorisation d'un administrateur."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Nom d'utilisateur administrateur")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Mot de passe")
        form.addRow("Administrateur", self.username)
        form.addRow("Mot de passe", self.password)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        confirm_btn = QPushButton("Autoriser")
        confirm_btn.setObjectName("Primary")
        confirm_btn.clicked.connect(self._authorize)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(confirm_btn)
        layout.addLayout(buttons)

        self.password.returnPressed.connect(self._authorize)

    def _authorize(self) -> None:
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            warn(self, "Saisissez le nom d'utilisateur et le mot de passe.")
            return
        if not AuthService.verify_admin_password(username, password):
            warn(self, "Identifiants administrateur invalides.")
            self.password.clear()
            self.password.setFocus()
            return
        self.authorized_username = username
        self.accept()


def require_admin_authorization(parent, reason: str = "") -> bool:
    """Ouvre le dialogue et retourne True si un admin a validé l'action."""
    dialog = AuthorizeDialog(reason=reason, parent=parent)
    return bool(dialog.exec())
