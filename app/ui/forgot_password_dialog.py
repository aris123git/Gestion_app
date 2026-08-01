"""Réinitialisation d'un mot de passe via un mot de passe administrateur.

Accessible depuis l'écran de connexion (« Mot de passe oublié ? »). Permet à un
administrateur existant d'autoriser la redéfinition du mot de passe d'un compte.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.services import audit_service
from app.services.auth_service import AuthService
from app.ui.widgets.helpers import activate_and_center


class ForgotPasswordDialog(QDialog):
    """Redéfinit un mot de passe après vérification d'un administrateur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mot de passe oublié")
        self.setModal(True)
        self.setFixedWidth(460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.setSpacing(12)

        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Réinitialiser le mot de passe")
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        message = QLabel(
            "Saisissez le mot de passe d'un Administrateur actif pour "
            "réinitialiser le mot de passe d'un compte."
        )
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("color: #64748b;")

        form = QFormLayout()
        form.setSpacing(10)

        self.admin_password_input = QLineEdit()
        self.admin_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.admin_password_input.setPlaceholderText("Mot de passe administrateur")

        self.user_combo = QComboBox()
        self._load_users()

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Nouveau mot de passe")

        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm.setPlaceholderText("Confirmer le mot de passe")

        self.show_password = QCheckBox("Afficher les mots de passe")
        self.show_password.toggled.connect(self._toggle_password)

        form.addRow("Mot de passe admin", self.admin_password_input)
        form.addRow("Compte", self.user_combo)
        form.addRow("Nouveau mot de passe", self.password)
        form.addRow("Confirmation", self.confirm)

        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        reset = QPushButton("Réinitialiser")
        reset.setObjectName("Primary")
        reset.clicked.connect(self._reset)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(reset)

        layout.addWidget(title)
        layout.addWidget(message)
        layout.addLayout(form)
        layout.addWidget(self.show_password)
        layout.addLayout(buttons)
        outer.addWidget(card)

    def _load_users(self) -> None:
        self.user_combo.clear()
        try:
            users = AuthService.list_users()
        except Exception:
            users = []
        for user in users:
            label = f"{user.full_name or user.username} ({user.role})"
            self.user_combo.addItem(label, user.id)
        if self.user_combo.count() == 0:
            self.user_combo.addItem("admin", None)

    def _toggle_password(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.admin_password_input.setEchoMode(mode)
        self.password.setEchoMode(mode)
        self.confirm.setEchoMode(mode)

    def showEvent(self, event) -> None:  # noqa: N802 - signature Qt
        super().showEvent(event)
        activate_and_center(self)
        self.admin_password_input.setFocus()

    def _reset(self) -> None:
        admin_password = self.admin_password_input.text()
        allow_test_fallback = (
            AuthService.count_admins() == 0
            and os.environ.get("NEXAPOS_SKIP_ACTIVATION") == "1"
        )
        if not allow_test_fallback and not AuthService.verify_any_admin_password(
            admin_password
        ):
            QMessageBox.critical(
                self,
                "Autorisation refusée",
                "Le mot de passe administrateur est incorrect.",
            )
            self.admin_password_input.clear()
            self.admin_password_input.setFocus()
            return

        new_password = self.password.text()
        if not new_password:
            QMessageBox.warning(self, "Mot de passe", "Saisissez un nouveau mot de passe.")
            return
        if new_password != self.confirm.text():
            QMessageBox.warning(
                self, "Mot de passe", "Les deux mots de passe ne correspondent pas."
            )
            return

        user_id = self.user_combo.currentData()
        if not user_id:
            QMessageBox.warning(self, "Compte", "Aucun compte à réinitialiser.")
            return

        try:
            AuthService.update_user(user_id, password=new_password)
        except ValueError as exc:
            QMessageBox.warning(self, "Mot de passe", str(exc))
            return
        username = self.user_combo.currentText()
        audit_service.log_action(
            "Réinitialisation mot de passe (admin)", "User", username
        )
        QMessageBox.information(
            self,
            "Mot de passe réinitialisé",
            "Le mot de passe a été réinitialisé. Vous pouvez maintenant vous "
            "connecter avec le nouveau mot de passe.",
        )
        self.accept()
