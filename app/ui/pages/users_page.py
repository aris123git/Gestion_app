"""Page de gestion des utilisateurs (administrateur uniquement)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.services.auth_service import AuthService
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, page_title, warn


class UserDialog(QDialog):
    """Formulaire de création / modification d'un utilisateur."""

    def __init__(self, user=None, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("Utilisateur")
        self.setModal(True)
        self.setMinimumWidth(400)
        self.data = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        form = QFormLayout()
        form.setSpacing(10)

        self.username = QLineEdit()
        self.full_name = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.role = QComboBox()
        self.role.addItems(config.ROLES)
        self.active = QCheckBox("Compte actif")
        self.active.setChecked(True)

        form.addRow("Nom d'utilisateur *", self.username)
        form.addRow("Nom complet", self.full_name)
        password_label = "Mot de passe *" if not user else "Nouveau mot de passe"
        form.addRow(password_label, self.password)
        form.addRow("Rôle", self.role)
        form.addRow("", self.active)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Enregistrer")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)

        if user:
            self.username.setText(user.username)
            self.username.setEnabled(False)
            self.full_name.setText(user.full_name)
            self.role.setCurrentText(user.role)
            self.active.setChecked(user.is_active)
            self.password.setPlaceholderText("Laisser vide pour ne pas changer")

    def _save(self) -> None:
        if not self.username.text().strip():
            warn(self, "Le nom d'utilisateur est obligatoire.")
            return
        if not self.user and not self.password.text():
            warn(self, "Le mot de passe est obligatoire.")
            return
        self.data = {
            "username": self.username.text().strip(),
            "full_name": self.full_name.text().strip(),
            "password": self.password.text(),
            "role": self.role.currentText(),
            "is_active": self.active.isChecked(),
        }
        self.accept()


class UsersPage(QWidget):
    HEADERS = ["Utilisateur", "Nom complet", "Rôle", "Actif"]

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.addWidget(page_title("Utilisateurs"))
        header.addStretch()
        add = QPushButton("+ Nouvel utilisateur")
        add.setObjectName("Primary")
        add.clicked.connect(self._add)
        header.addWidget(add)
        layout.addLayout(header)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._edit)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        actions.addStretch()
        edit = QPushButton("Modifier")
        edit.clicked.connect(self._edit)
        delete = QPushButton("Supprimer")
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete)
        actions.addWidget(edit)
        actions.addWidget(delete)
        layout.addLayout(actions)

    def _guard_admin(self) -> bool:
        if not self.state.is_admin:
            warn(self, "Seul un administrateur peut gérer les utilisateurs.")
            return False
        return True

    def refresh(self) -> None:
        users = AuthService.list_users()
        self._ids = [u.id for u in users]
        self.table.setRowCount(len(users))
        for row, user in enumerate(users):
            self.table.setItem(row, 0, QTableWidgetItem(user.username))
            self.table.setItem(row, 1, QTableWidgetItem(user.full_name))
            self.table.setItem(row, 2, QTableWidgetItem(user.role))
            self.table.setItem(row, 3, QTableWidgetItem("Oui" if user.is_active else "Non"))

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _add(self) -> None:
        if not self._guard_admin():
            return
        dialog = UserDialog(parent=self)
        if dialog.exec() and dialog.data:
            AuthService.create_user(
                dialog.data["username"],
                dialog.data["password"],
                dialog.data["full_name"],
                dialog.data["role"],
            )
            self.refresh()

    def _edit(self) -> None:
        if not self._guard_admin():
            return
        user_id = self._selected_id()
        if not user_id:
            warn(self, "Sélectionnez un utilisateur.")
            return
        user = next((u for u in AuthService.list_users() if u.id == user_id), None)
        dialog = UserDialog(user=user, parent=self)
        if dialog.exec() and dialog.data:
            AuthService.update_user(
                user_id,
                full_name=dialog.data["full_name"],
                role=dialog.data["role"],
                is_active=dialog.data["is_active"],
                password=dialog.data["password"] or None,
            )
            self.refresh()

    def _delete(self) -> None:
        if not self._guard_admin():
            return
        user_id = self._selected_id()
        if not user_id:
            warn(self, "Sélectionnez un utilisateur.")
            return
        if user_id == self.state.user_id:
            warn(self, "Vous ne pouvez pas supprimer votre propre compte.")
            return
        if confirm(self, "Supprimer cet utilisateur ?"):
            AuthService.delete_user(user_id)
            self.refresh()
