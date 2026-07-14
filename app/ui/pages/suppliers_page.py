"""Page de gestion des fournisseurs (CRUD, recherche)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.controllers.supplier_controller import SupplierController
from app.ui.dialogs.contact_dialog import ContactDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, page_title, warn


class SuppliersPage(QWidget):
    HEADERS = ["Nom", "Téléphone", "Adresse", "Email"]

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.addWidget(page_title("Fournisseurs"))
        header.addStretch()
        add = QPushButton("+ Nouveau fournisseur")
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
        edit = QPushButton("Modifier")
        edit.clicked.connect(self._edit)
        delete = QPushButton("Supprimer")
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete)
        actions.addWidget(edit)
        actions.addWidget(delete)
        layout.addLayout(actions)

    def refresh(self) -> None:
        suppliers = SupplierController.list(self.search.text().strip())
        self._ids = [s.id for s in suppliers]
        self.table.setRowCount(len(suppliers))
        for row, supplier in enumerate(suppliers):
            self.table.setItem(row, 0, QTableWidgetItem(supplier.name))
            self.table.setItem(row, 1, QTableWidgetItem(supplier.phone))
            self.table.setItem(row, 2, QTableWidgetItem(supplier.address))
            self.table.setItem(row, 3, QTableWidgetItem(supplier.email))

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _add(self) -> None:
        dialog = ContactDialog("Nouveau fournisseur", parent=self)
        if dialog.exec() and dialog.data:
            SupplierController.create(dialog.data)
            self.refresh()

    def _edit(self) -> None:
        supplier_id = self._selected_id()
        if not supplier_id:
            warn(self, "Sélectionnez un fournisseur.")
            return
        supplier = SupplierController.get(supplier_id)
        dialog = ContactDialog("Modifier le fournisseur", supplier, parent=self)
        if dialog.exec() and dialog.data:
            SupplierController.update(supplier_id, dialog.data)
            self.refresh()

    def _delete(self) -> None:
        supplier_id = self._selected_id()
        if not supplier_id:
            warn(self, "Sélectionnez un fournisseur.")
            return
        if confirm(self, "Supprimer ce fournisseur ?"):
            SupplierController.delete(supplier_id)
            self.refresh()
