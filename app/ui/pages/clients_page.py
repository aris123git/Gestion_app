"""Page de gestion des clients (CRUD, dettes, historique)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
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
from app.services.loyalty_service import LoyaltyService
from app.ui.dialogs.contact_dialog import ContactDialog
from app.ui.dialogs.debt_history_dialog import DebtHistoryDialog
from app.ui.dialogs.debt_payment_dialog import DebtPaymentDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, page_title, warn
from app.utils.helpers import format_money, format_quantity


class ClientsPage(QWidget):
    HEADERS = [
        "Nom",
        "Téléphone",
        "Adresse",
        "Dette",
        "Dettes actives",
        "Points",
        "Dernière visite",
        "Achats",
    ]

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
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _text="": self._search_timer.start())
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
            ("Échanger points", self._redeem_points, "Primary"),
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
        client_ids = [client.id for client in clients]
        debt_summaries = DebtService.summaries_for_clients(client_ids)

        rows_data = []
        for client in clients:
            summary = debt_summaries.get(
                client.id,
                {
                    "total_remaining": 0.0,
                    "active_count": 0,
                    "overdue_count": 0,
                    "debts": [],
                },
            )
            if mode == "with_debt" and summary["total_remaining"] <= 0:
                continue
            if mode == "overdue" and summary["overdue_count"] <= 0:
                continue
            rows_data.append((client, summary))

        # Recherche étendue via notes / statut de dette.
        search = self.search.text().strip()
        if search:
            seen = {c.id for c, _ in rows_data}
            extra_clients = []
            for debt in DebtService.list_debts(search=search, limit=300):
                if debt.client_id in seen:
                    continue
                client = ClientController.get(debt.client_id)
                if not client:
                    continue
                extra_clients.append(client)
                seen.add(client.id)
            extra_summaries = DebtService.summaries_for_clients(
                [client.id for client in extra_clients]
            )
            for client in extra_clients:
                summary = extra_summaries.get(
                    client.id,
                    {
                        "total_remaining": 0.0,
                        "active_count": 0,
                        "overdue_count": 0,
                        "debts": [],
                    },
                )
                if mode == "with_debt" and summary["total_remaining"] <= 0:
                    continue
                if mode == "overdue" and summary["overdue_count"] <= 0:
                    continue
                rows_data.append((client, summary))

        self._ids = [c.id for c, _ in rows_data]
        loyalty_balances = LoyaltyService.balances_for_clients(self._ids)
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
            self.table.setItem(
                row,
                5,
                QTableWidgetItem(format_quantity(loyalty_balances.get(client.id, 0.0))),
            )
            self.table.setItem(row, 6, QTableWidgetItem(client.last_visit or ""))
            self.table.setItem(row, 7, QTableWidgetItem(str(client.purchase_count or 0)))

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def select_client(self, client_id: int) -> None:
        if client_id not in self._ids:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.debt_filter.setCurrentIndex(0)
            self.refresh()
        if client_id in self._ids:
            row = self._ids.index(client_id)
            self.table.selectRow(row)
            item = self.table.item(row, 0)
            if item:
                self.table.scrollToItem(item)

    def _add(self) -> None:
        can_manage_debts = self.state.can(perms.MANAGE_CLIENT_DEBTS)
        dialog = ContactDialog(
            "Nouveau client", with_debt=can_manage_debts, parent=self
        )
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
        can_manage_debts = self.state.can(perms.MANAGE_CLIENT_DEBTS)
        dialog = ContactDialog(
            "Modifier le client", client, with_debt=can_manage_debts, parent=self
        )
        if dialog.exec() and dialog.data:
            ClientController.update(client_id, dialog.data)
            self.refresh()
            self.state.notify_data_changed()

    def _settle(self) -> None:
        if not self.state.can(perms.MANAGE_CLIENT_DEBTS):
            warn(self, "Vous n'avez pas l'autorisation de gérer les dettes client.")
            return
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

    def _redeem_points(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, "Sélectionnez un client.")
            return
        client = ClientController.get(client_id)
        if not client:
            return
        balance = LoyaltyService.get_balance(client_id)
        if balance <= 0:
            warn(self, "Ce client n'a aucun point de fidélité.")
            return
        from PySide6.QtWidgets import QInputDialog

        points, ok = QInputDialog.getDouble(
            self,
            "Échanger des points",
            f"Points disponibles : {balance:g}\nNombre à échanger :",
            min(balance, 100.0),
            0.01,
            balance,
            2,
        )
        if not ok or points <= 0:
            return
        try:
            remaining = LoyaltyService.redeem(
                client_id,
                points,
                user_id=self.state.user_id,
                username=getattr(self.state.current_user, "username", ""),
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        info(self, f"Échange enregistré. Solde restant : {remaining:g} pts.")

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
        if not self.state.can(perms.MANAGE_CLIENTS):
            warn(self, "Vous n'avez pas l'autorisation de supprimer un client.")
            return
        if DebtService.list_debts(client_id=client_id, limit=1):
            warn(
                self,
                "Impossible de supprimer un client ayant un historique de dettes. "
                "Réglez ou conservez la fiche pour la traçabilité.",
            )
            return
        if ClientController.has_sales(client_id):
            warn(
                self,
                "Impossible de supprimer un client ayant un historique de ventes. "
                "Conservez la fiche pour la traçabilité.",
            )
            return
        if confirm(self, "Supprimer ce client ?"):
            try:
                ClientController.delete(client_id)
            except ValueError as exc:
                warn(self, str(exc))
                return
            self.refresh()
            self.state.notify_data_changed()
