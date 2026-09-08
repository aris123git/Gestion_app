"""Page Avoirs clients (Gestion App + Maquis Caisse)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.avoir_service import AvoirService
from app.services import settings_service
from app.ui.widgets.helpers import confirm, info, warn
from app.utils.helpers import format_money


class AvoirsPage(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Avoirs clients")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        layout.addWidget(
            QLabel(
                "Bons d'avoir (crédit magasin) utilisables comme paiement. "
                "Commun à Gestion App et Maquis Caisse."
            )
        )

        form_row = QHBoxLayout()
        form = QFormLayout()
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("Nom du client (optionnel)")
        self.amount = QDoubleSpinBox()
        self.amount.setRange(1, 50_000_000)
        self.amount.setDecimals(0)
        self.amount.setValue(1000)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Motif (rendu monnaie, geste commercial…)")
        form.addRow("Client", self.customer)
        form.addRow("Montant", self.amount)
        form.addRow("Motif", self.reason)
        form_row.addLayout(form, 1)
        create_btn = QPushButton("Créer l'avoir")
        create_btn.setObjectName("Primary")
        create_btn.clicked.connect(self._create)
        form_row.addWidget(create_btn, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(form_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["N°", "Client", "Montant", "Reste", "Statut", "Motif"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        redeem = QPushButton("Utiliser (tout le reste)")
        redeem.clicked.connect(self._redeem_selected)
        cancel = QPushButton("Annuler l'avoir")
        cancel.clicked.connect(self._cancel_selected)
        refresh = QPushButton("Actualiser")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(redeem)
        actions.addWidget(cancel)
        actions.addStretch()
        actions.addWidget(refresh)
        layout.addLayout(actions)

        self._ids: list[int] = []
        self.refresh()

    def refresh(self) -> None:
        currency = settings_service.get_shop_info().currency or "FCFA"
        rows = AvoirService.list(limit=200)
        self._ids = [a.id for a in rows]
        self.table.setRowCount(len(rows))
        for i, a in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(a.id)))
            self.table.setItem(
                i, 1, QTableWidgetItem(a.customer_name or (f"Client #{a.client_id}" if a.client_id else "—"))
            )
            self.table.setItem(
                i, 2, QTableWidgetItem(format_money(float(a.amount_initial), currency))
            )
            self.table.setItem(
                i, 3, QTableWidgetItem(format_money(float(a.amount_remaining), currency))
            )
            self.table.setItem(i, 4, QTableWidgetItem(a.status))
            self.table.setItem(i, 5, QTableWidgetItem(a.reason or a.note or ""))

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _create(self) -> None:
        try:
            user = getattr(self.state, "current_user", None)
            AvoirService.create(
                amount=float(self.amount.value()),
                customer_name=self.customer.text().strip(),
                reason=self.reason.text().strip(),
                created_by=getattr(user, "id", None),
            )
            self.customer.clear()
            self.reason.clear()
            self.refresh()
            info(self, "Avoir créé.")
        except Exception as exc:
            warn(self, str(exc))

    def _redeem_selected(self) -> None:
        avoir_id = self._selected_id()
        if not avoir_id:
            warn(self, "Sélectionnez un avoir.")
            return
        avoir = AvoirService.get(avoir_id)
        if not avoir:
            return
        remaining = float(avoir.amount_remaining)
        if remaining <= 0:
            warn(self, "Plus rien à utiliser sur cet avoir.")
            return
        if not confirm(self, f"Utiliser les {remaining:.0f} restants ?", "Avoir"):
            return
        try:
            AvoirService.redeem(avoir_id, remaining, note="Utilisation manuelle")
            self.refresh()
            info(self, "Avoir soldé.")
        except Exception as exc:
            warn(self, str(exc))

    def _cancel_selected(self) -> None:
        avoir_id = self._selected_id()
        if not avoir_id:
            warn(self, "Sélectionnez un avoir.")
            return
        if not confirm(self, "Annuler cet avoir ?", "Avoir"):
            return
        try:
            AvoirService.cancel(avoir_id)
            self.refresh()
        except Exception as exc:
            warn(self, str(exc))
