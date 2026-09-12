"""Page de gestion des catégories et des unités."""

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

from app.controllers.category_controller import CategoryController
from app.controllers.unit_controller import UnitController
from app.i18n import t
from app.services import permissions as perms
from app.ui.dialogs.category_dialog import CategoryDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, make_card, page_title, section_title, warn


class CategoriesPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._cat_ids: list[int] = []
        self._unit_ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(page_title(t("categories.title")))

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._build_categories(), 2)
        columns.addWidget(self._build_units(), 1)
        layout.addLayout(columns)

    # --- Catégories --------------------------------------------------------
    def _build_categories(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(section_title(t("categories.section")))

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("common.search"))
        self.search.textChanged.connect(self.refresh)
        add = QPushButton("+ " + t("common.add"))
        add.setObjectName("Primary")
        add.clicked.connect(self._add_category)
        row.addWidget(self.search)
        row.addWidget(add)
        layout.addLayout(row)

        self.cat_table = QTableWidget(0, 2)
        self.cat_table.setHorizontalHeaderLabels(
            [t("categories.name"), t("categories.description")]
        )
        self.cat_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.cat_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cat_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cat_table.doubleClicked.connect(self._edit_category)
        layout.addWidget(self.cat_table)

        actions = QHBoxLayout()
        actions.addStretch()
        edit = QPushButton(t("common.edit"))
        edit.clicked.connect(self._edit_category)
        delete = QPushButton(t("common.delete"))
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete_category)
        actions.addWidget(edit)
        actions.addWidget(delete)
        layout.addLayout(actions)
        return make_card(wrap)

    def _add_category(self) -> None:
        dialog = CategoryDialog(parent=self)
        if dialog.exec() and dialog.data:
            CategoryController.create(dialog.data["name"], dialog.data["description"])
            self.refresh()
            self.state.notify_data_changed()

    def _selected_category(self):
        row = self.cat_table.currentRow()
        if row < 0 or row >= len(self._cat_ids):
            return None
        return self._cat_ids[row]

    def _edit_category(self) -> None:
        cat_id = self._selected_category()
        if not cat_id:
            warn(self, "Sélectionnez une catégorie.")
            return
        category = CategoryController.get(cat_id)
        dialog = CategoryDialog(category=category, parent=self)
        if dialog.exec() and dialog.data:
            CategoryController.update(
                cat_id, dialog.data["name"], dialog.data["description"]
            )
            self.refresh()
            self.state.notify_data_changed()

    def _delete_category(self) -> None:
        cat_id = self._selected_category()
        if not cat_id:
            warn(self, "Sélectionnez une catégorie.")
            return
        if not self.state.can(perms.MANAGE_CATEGORIES):
            warn(self, "Vous n'avez pas l'autorisation de supprimer une catégorie.")
            return
        if confirm(self, "Supprimer cette catégorie ? Les produits seront conservés."):
            CategoryController.delete(cat_id)
            self.refresh()
            self.state.notify_data_changed()

    # --- Unités ------------------------------------------------------------
    def _build_units(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(section_title(t("categories.units")))

        add = QPushButton("+ " + t("common.add"))
        add.setObjectName("Primary")
        add.clicked.connect(self._add_unit)
        layout.addWidget(add)

        self.unit_table = QTableWidget(0, 2)
        self.unit_table.setHorizontalHeaderLabels(
            [t("categories.units"), "Type"]
        )
        self.unit_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.unit_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.unit_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.unit_table)

        delete = QPushButton(t("common.delete"))
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete_unit)
        layout.addWidget(delete)
        return make_card(wrap)

    def _add_unit(self) -> None:
        name, ok = QInputDialog.getText(self, "Nouvelle unité", "Nom de l'unité :")
        if ok and name.strip():
            UnitController.create(name.strip())
            self.refresh()

    def _delete_unit(self) -> None:
        row = self.unit_table.currentRow()
        if row < 0 or row >= len(self._unit_ids):
            warn(self, "Sélectionnez une unité.")
            return
        if not self.state.can(perms.MANAGE_CATEGORIES):
            warn(self, "Vous n'avez pas l'autorisation de supprimer une unité.")
            return
        UnitController.delete(self._unit_ids[row])
        self.refresh()

    # --- Rafraîchissement --------------------------------------------------
    def refresh(self) -> None:
        categories = CategoryController.list(self.search.text().strip())
        self._cat_ids = [c.id for c in categories]
        self.cat_table.setRowCount(len(categories))
        for row, category in enumerate(categories):
            self.cat_table.setItem(row, 0, QTableWidgetItem(category.name))
            self.cat_table.setItem(row, 1, QTableWidgetItem(category.description))

        units = UnitController.list()
        self._unit_ids = [u.id for u in units]
        self.unit_table.setRowCount(len(units))
        for row, unit in enumerate(units):
            self.unit_table.setItem(row, 0, QTableWidgetItem(unit.name))
            self.unit_table.setItem(
                row, 1, QTableWidgetItem("Par défaut" if unit.is_default else "Personnalisée")
            )
