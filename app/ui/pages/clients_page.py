"""Page de gestion des clients (CRUD, dettes, historique)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.controllers.client_controller import ClientController
from app.services import permissions as perms, settings_service
from app.services.debt_service import DebtService
from app.ui.dialogs.contact_dialog import ContactDialog
from app.ui.dialogs.debt_history_dialog import DebtHistoryDialog
from app.ui.dialogs.debt_payment_dialog import DebtPaymentDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, page_title, warn
from app.utils.helpers import format_money


class ClientsPage(QWidget):
    HEADERS = ["Nom", "Téléphone", "Adresse", "Dette", "Dettes actives"]

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

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (nom, téléphone, note de dette)…")
        self.search.textChanged.connect(self.refresh)
        self.debt_filter = QComboBox()
        self.debt_filter.addItem("Tous les clients", "all")
        self.debt_filter.addItem("Avec dette", "with_debt")
        self.debt_filter.addItem("Dettes échues", "overdue")
        self.debt_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.search, 3)
        filters.addWidget(self.debt_filter, 1)
        layout.addLayout(filters)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._edit)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        actions.addStretch()
        for label, handler, obj in [
            ("Modifier", self._edit, ""),
            ("Régler dette", self._settle, "Success"),
            ("Historique dettes", self._history, "Primary"),
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
        mode = self.debt_filter.currentData()
        currency = settings_service.get_currency()

        rows_data = []
        for client in clients:
            summary = DebtService.client_summary(client.id)
            if mode == "with_debt" and summary["total_remaining"] <= 0:
                continue
            if mode == "overdue" and summary["overdue_count"] <= 0:
                continue
            rows_data.append((client, summary))

        # Recherche étendue via notes / statut de dette.
        search = self.search.text().strip()
        if search:
            seen = {c.id for c, _ in rows_data}
            for debt in DebtService.list_debts(search=search, limit=300):
                if debt.client_id in seen:
                    continue
                client = ClientController.get(debt.client_id)
                if not client:
                    continue
                summary = DebtService.client_summary(client.id)
                if mode == "with_debt" and summary["total_remaining"] <= 0:
                    continue
                if mode == "overdue" and summary["overdue_count"] <= 0:
                    continue
                rows_data.append((client, summary))
                seen.add(client.id)

        self._ids = [c.id for c, _ in rows_data]
        self.table.setRowCount(len(rows_data))
        for row, (client, summary) in enumerate(rows_data):
            self.table.setItem(row, 0, QTableWidgetItem(client.name))
            self.table.setItem(row, 1, QTableWidgetItem(client.phone))
            self.table.setItem(row, 2, QTableWidgetItem(client.address))
            debt_item = QTableWidgetItem(
                format_money(summary["total_remaining"], currency)
            )
            if summary["overdue_count"] > 0:
                debt_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 3, debt_item)
            self.table.setItem(
                row, 4, QTableWidgetItem(str(summary["active_count"]))
            )

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _add(self) -> None:
        dialog = ContactDialog("Nouveau client", with_debt=True, parent=self)
        if dialog.exec() and dialog.data:
            ClientController.create(
                dialog.data,
                user_id=self.state.user_id,
                username=getattr(self.state.current_user, "username", ""),
            )
            self.refresh()
            self.state.notify_data_changed()

    def _edit(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, "Sélectionnez un client.")
            return
        client = ClientController.get(client_id)
        dialog = ContactDialog(
            "Modifier le client", client, with_debt=True, parent=self
        )
        if dialog.exec() and dialog.data:
            ClientController.update(client_id, dialog.data)
            self.refresh()
            self.state.notify_data_changed()

    def _settle(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, "Sélectionnez un client.")
            return
        client = ClientController.get(client_id)
        if not client:
            return
        summary = DebtService.client_summary(client_id)
        if summary["total_remaining"] <= 0:
            warn(self, "Ce client n'a aucune dette active.")
            return
        dialog = DebtPaymentDialog(
            client.name, summary["total_remaining"], parent=self
        )
        if not dialog.exec() or not dialog.result_data:
            return
        try:
            ClientController.settle_debt(
                client_id,
                dialog.result_data["amount"],
                payment_method=dialog.result_data["payment_method"],
                note=dialog.result_data["note"],
                user_id=self.state.user_id,
                username=getattr(self.state.current_user, "username", ""),
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        self.state.notify_data_changed()
        info(self, "Remboursement enregistré.")

    def _history(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, "Sélectionnez un client.")
            return
        client = ClientController.get(client_id)
        if not client:
            return
        DebtHistoryDialog(client_id, client.name, parent=self).exec()

    def _delete(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, "Sélectionnez un client.")
            return
        if not (self.state.is_admin or self.state.can(perms.MANAGE_PRODUCTS)):
            warn(self, "Vous n'avez pas l'autorisation de supprimer un client.")
            return
        if DebtService.list_debts(client_id=client_id, limit=1):
            warn(
                self,
                "Impossible de supprimer un client ayant un historique de dettes. "
                "Réglez ou conservez la fiche pour la traçabilité.",
            )
            return
        if confirm(self, "Supprimer ce client ?"):
            ClientController.delete(client_id)
            self.refresh()
            self.state.notify_data_changed()
