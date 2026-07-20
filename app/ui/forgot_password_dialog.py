"""Réinitialisation d'un mot de passe via le code d'activation maître.

Accessible depuis l'écran de connexion (« Mot de passe oublié ? »). Permet, sans
accès Internet, de redéfinir le mot de passe d'un compte en saisissant le code
d'activation maître du logiciel. Utile pour dépanner un client qui a perdu son
mot de passe administrateur.
"""

from __future__ import annotations

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

from app.services import activation_service, audit_service
from app.services.auth_service import AuthService
from app.ui.widgets.helpers import activate_and_center


class ForgotPasswordDialog(QDialog):
    """Redéfinit le mot de passe d'un compte après vérification du code maître."""

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
            "Saisissez le code d'activation du logiciel pour réinitialiser le "
            "mot de passe d'un compte."
        )
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("color: #64748b;")

        form = QFormLayout()
        form.setSpacing(10)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Code d'activation")

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

        form.addRow("Code d'activation", self.code_input)
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
        self.password.setEchoMode(mode)
        self.confirm.setEchoMode(mode)

    def showEvent(self, event) -> None:  # noqa: N802 - signature Qt
        super().showEvent(event)
        activate_and_center(self)
        self.code_input.setFocus()

    def _reset(self) -> None:
        code = self.code_input.text().strip()
        if not activation_service.verify_code(code):
            QMessageBox.critical(
                self, "Code invalide", "Le code d'activation est incorrect."
            )
            self.code_input.clear()
            self.code_input.setFocus()
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

        AuthService.update_user(user_id, password=new_password)
        username = self.user_combo.currentText()
        audit_service.log_action(
            "Réinitialisation mot de passe (code maître)", "User", username
        )
        QMessageBox.information(
            self,
            "Mot de passe réinitialisé",
            "Le mot de passe a été réinitialisé. Vous pouvez maintenant vous "
            "connecter avec le nouveau mot de passe.",
        )
        self.accept()
