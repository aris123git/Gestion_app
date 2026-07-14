"""Page de gestion des clients (CRUD, dettes, historique)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.controllers.client_controller import ClientController
from app.services import settings_service
from app.ui.dialogs.contact_dialog import ContactDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, page_title, warn
from app.utils.helpers import format_money


class ClientsPage(QWidget):
    HEADERS = ["Nom", "Téléphone", "Adresse", "Dette"]

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.addWidget(page_title("Clients"))
        header.addStretch()
        add = QPushButton("+ Nouveau client")
        add.setObjectName("Primary")
        add.clicked.connect(self._add)
        header.addWidget(add)
        layout.addLayout(header)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (nom, téléphone)…")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._edit)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        actions.addStretch()
        for label, handler, obj in [
            ("Modifier", self._edit, ""),
            ("Régler dette", self._settle, "Success"),
            ("Supprimer", self._delete, "Danger"),
        ]:
            button = QPushButton(label)
            if obj:
                button.setObjectName(obj)
            button.clicked.connect(handler)
            actions.addWidget(button)
        layout.addLayout(actions)

    def refresh(self) -> None:
        clients = ClientController.list(self.search.text().strip())
        currency = settings_service.get_currency()
        self._ids = [c.id for c in clients]
        self.table.setRowCount(len(clients))
        for row, client in enumerate(clients):
            self.table.setItem(row, 0, QTableWidgetItem(client.name))
            self.table.setItem(row, 1, QTableWidgetItem(client.phone))
            self.table.setItem(row, 2, QTableWidgetItem(client.address))
            self.table.setItem(row, 3, QTableWidgetItem(format_money(client.debt, currency)))

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _add(self) -> None:
        dialog = ContactDialog("Nouveau client", with_debt=True, parent=self)
        if dialog.exec() and dialog.data:
            ClientController.create(dialog.data)
            self.refresh()
            self.state.notify_data_changed()

    def _edit(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, "Sélectionnez un client.")
            return
        client = ClientController.get(client_id)
        dialog = ContactDialog("Modifier le client", client, with_debt=True, parent=self)
        if dialog.exec() and dialog.data:
            ClientController.update(client_id, dialog.data)
            self.refresh()
            self.state.notify_data_changed()

    def _settle(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, "Sélectionnez un client.")
            return
        amount, ok = QInputDialog.getDouble(
            self, "Règlement de dette", "Montant réglé :", 0, 0, 1_000_000_000, 0
        )
        if ok and amount > 0:
            ClientController.settle_debt(client_id, amount)
            self.refresh()
            info(self, "Règlement enregistré.")

    def _delete(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, "Sélectionnez un client.")
            return
        if confirm(self, "Supprimer ce client ?"):
            ClientController.delete(client_id)
            self.refresh()
            self.state.notify_data_changed()
