"""Page de gestion du stock : entrées, sorties, inventaire, corrections, historique."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.controllers.product_controller import ProductController
from app.controllers.stock_controller import StockController
from app.services import audit_service
from app.ui.state import AppState
from app.ui.widgets.helpers import info, make_card, page_title, warn
from app.utils.helpers import format_datetime, format_quantity


class StockPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(page_title("Gestion du stock"))

        tabs = QTabWidget()
        tabs.addTab(self._build_movement_tab(), "Mouvements")
        tabs.addTab(self._build_history_tab(), "Historique")
        tabs.currentChanged.connect(lambda _: self._reload_history())
        layout.addWidget(tabs)

    # --- Onglet mouvements -------------------------------------------------
    def _build_movement_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 12, 0, 0)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setSpacing(10)

        self.product_combo = QComboBox()
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0, 10_000_000)
        self.quantity.setDecimals(3)
        self.unit_cost = QDoubleSpinBox()
        self.unit_cost.setRange(0, 1_000_000_000)
        self.unit_cost.setDecimals(0)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Motif (facultatif)")

        form.addRow("Produit", self.product_combo)
        form.addRow("Quantité", self.quantity)
        form.addRow("Coût unitaire (entrée)", self.unit_cost)
        form.addRow("Motif", self.reason)
        layout.addWidget(make_card(form_widget))

        buttons = QHBoxLayout()
        for label, handler, obj in [
            ("Entrée (+)", self._stock_in, "Success"),
            ("Sortie (-)", self._stock_out, "Danger"),
            ("Inventaire (=)", self._inventory, "Primary"),
            ("Correction", self._correction, ""),
        ]:
            button = QPushButton(label)
            if obj:
                button.setObjectName(obj)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addStretch()
        return wrap

    def _build_history_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 12, 0, 0)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(
            ["Date", "Produit", "Type", "Quantité", "Stock après"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.history_table)
        return wrap

    # --- Actions -----------------------------------------------------------
    def _current_product_id(self):
        return self.product_combo.currentData()

    def _stock_in(self) -> None:
        pid = self._current_product_id()
        if not pid or self.quantity.value() <= 0:
            warn(self, "Choisissez un produit et une quantité.")
            return
        StockController.stock_in(
            pid, self.quantity.value(), self.unit_cost.value(),
            self.reason.text(), self.state.user_id,
        )
        self._after_movement("Entrée de stock", pid)

    def _stock_out(self) -> None:
        pid = self._current_product_id()
        if not pid or self.quantity.value() <= 0:
            warn(self, "Choisissez un produit et une quantité.")
            return
        StockController.stock_out(
            pid, self.quantity.value(), self.reason.text(), self.state.user_id
        )
        self._after_movement("Sortie de stock", pid)

    def _inventory(self) -> None:
        pid = self._current_product_id()
        if not pid:
            warn(self, "Choisissez un produit.")
            return
        StockController.set_inventory(
            pid, self.quantity.value(), self.reason.text(), self.state.user_id
        )
        self._after_movement("Inventaire", pid)

    def _correction(self) -> None:
        pid = self._current_product_id()
        if not pid:
            warn(self, "Choisissez un produit.")
            return
        StockController.correct(
            pid, self.quantity.value(), self.reason.text(), self.state.user_id
        )
        self._after_movement("Correction", pid)

    def _after_movement(self, label: str, pid: int) -> None:
        audit_service.log_action(
            label, "Stock", f"produit={pid}",
            self.state.user_id, getattr(self.state.current_user, "username", ""),
        )
        self.quantity.setValue(0)
        self.unit_cost.setValue(0)
        self.reason.clear()
        self._reload_products()
        self._reload_history()
        self.state.notify_data_changed()
        info(self, f"{label} enregistré(e).")

    # --- Rafraîchissement --------------------------------------------------
    def refresh(self) -> None:
        self._reload_products()
        self._reload_history()

    def _reload_products(self) -> None:
        current = self.product_combo.currentData()
        self.product_combo.blockSignals(True)
        self.product_combo.clear()
        for product in ProductController.list(only_active=False):
            self.product_combo.addItem(
                f"{product.name} (stock: {format_quantity(product.quantity)})", product.id
            )
        index = self.product_combo.findData(current)
        if index >= 0:
            self.product_combo.setCurrentIndex(index)
        self.product_combo.blockSignals(False)

    def _reload_history(self) -> None:
        movements = StockController.history(limit=300)
        self.history_table.setRowCount(len(movements))
        for row, movement in enumerate(movements):
            product_name = movement.product.name if movement.product else "—"
            self.history_table.setItem(row, 0, QTableWidgetItem(format_datetime(movement.date)))
            self.history_table.setItem(row, 1, QTableWidgetItem(product_name))
            self.history_table.setItem(row, 2, QTableWidgetItem(movement.movement_type))
            self.history_table.setItem(row, 3, QTableWidgetItem(format_quantity(movement.quantity)))
            self.history_table.setItem(row, 4, QTableWidgetItem(format_quantity(movement.quantity_after)))
