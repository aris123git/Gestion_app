"""Page de gestion du stock : entrées, sorties, inventaire, corrections, historique."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
from app.controllers.supplier_controller import SupplierController
from app.services import audit_service, permissions as perms
from app.services.inventory_service import InventoryService
from app.ui.responsive import LayoutProfile, STOCK_HISTORY_COLUMNS, TableColumnController
from app.ui.state import AppState
from app.ui.widgets.helpers import info, make_card, page_title, warn
from app.utils.helpers import format_datetime, format_quantity


class StockPage(QWidget):
    HISTORY_LIMIT = 1000
    HISTORY_HEADERS = [
        "Date",
        "Utilisateur",
        "Produit",
        "Mouvement",
        "Quantité",
        "Stock après",
        "Fournisseur",
        "N° facture",
        "Motif",
        "Commentaire",
    ]

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
        self.supplier_combo = QComboBox()
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0, 10_000_000)
        self.quantity.setDecimals(3)
        self.unit_cost = QDoubleSpinBox()
        self.unit_cost.setRange(0, 1_000_000_000)
        self.unit_cost.setDecimals(0)
        self.invoice_number = QLineEdit()
        self.invoice_number.setPlaceholderText("Facultatif")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Ex. : Livraison fournisseur")
        self.loss_reason = QComboBox()
        self.loss_reason.addItems(InventoryService.loss_reasons())
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Facultatif")

        form.addRow("Produit", self.product_combo)
        form.addRow("Fournisseur", self.supplier_combo)
        form.addRow("N° facture", self.invoice_number)
        form.addRow("Quantité", self.quantity)
        form.addRow("Coût unitaire (entrée)", self.unit_cost)
        form.addRow("Motif", self.reason)
        form.addRow("Motif de perte", self.loss_reason)
        form.addRow("Commentaire", self.comment)
        layout.addWidget(make_card(form_widget))

        buttons = QHBoxLayout()
        for label, handler, obj in [
            ("Entrée (+)", self._stock_in, "Success"),
            ("Sortie (-)", self._stock_out, "Danger"),
            ("Perte (motif)", self._record_loss, "Danger"),
            ("Inventaire (=)", self._inventory, "Primary"),
            ("Ajustement / correction", self._correction, ""),
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
        self.history_note = QLabel("")
        self.history_note.setStyleSheet("color: #b45309; font-size: 12px;")
        self.history_note.setWordWrap(True)
        layout.addWidget(self.history_note)
        self.history_table = QTableWidget(0, len(self.HISTORY_HEADERS))
        self.history_table.setHorizontalHeaderLabels(self.HISTORY_HEADERS)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        layout.addWidget(self.history_table)
        self._history_columns = TableColumnController(
            self.history_table, STOCK_HISTORY_COLUMNS
        )
        self.state.layout_changed.connect(self._on_layout_changed)
        if self.state.layout is not None:
            self._on_layout_changed(self.state.layout)
        return wrap

    def _on_layout_changed(self, profile: LayoutProfile) -> None:
        if hasattr(self, "_history_columns"):
            self._history_columns.apply(profile.content_width)

    # --- Actions -----------------------------------------------------------
    def _current_product_id(self):
        return self.product_combo.currentData()

    def _current_supplier_id(self):
        return self.supplier_combo.currentData()

    def _ensure_stock_permission(self) -> bool:
        if self.state.can(perms.MANAGE_STOCK):
            return True
        warn(self, "Vous n'avez pas l'autorisation de modifier le stock.")
        return False

    def _stock_in(self) -> None:
        if not self._ensure_stock_permission():
            return
        pid = self._current_product_id()
        if not pid or self.quantity.value() <= 0:
            warn(self, "Choisissez un produit et une quantité.")
            return
        motif = self.reason.text().strip() or "Livraison fournisseur"
        StockController.stock_in(
            pid,
            self.quantity.value(),
            self.unit_cost.value(),
            motif,
            self.state.user_id,
            supplier_id=self._current_supplier_id(),
            invoice_number=self.invoice_number.text(),
            comment=self.comment.text(),
        )
        self._after_movement("Entrée de stock", pid)

    def _stock_out(self) -> None:
        if not self._ensure_stock_permission():
            return
        pid = self._current_product_id()
        if not pid or self.quantity.value() <= 0:
            warn(self, "Choisissez un produit et une quantité.")
            return
        StockController.stock_out(
            pid,
            self.quantity.value(),
            self.reason.text().strip() or "Sortie de stock",
            self.state.user_id,
            comment=self.comment.text(),
        )
        self._after_movement("Sortie de stock", pid)

    def _record_loss(self) -> None:
        if not self._ensure_stock_permission():
            return
        pid = self._current_product_id()
        if not pid or self.quantity.value() <= 0:
            warn(self, "Choisissez un produit et une quantité.")
            return
        try:
            InventoryService.record_loss(
                pid,
                self.quantity.value(),
                self.loss_reason.currentText(),
                comment=self.comment.text(),
                user_id=self.state.user_id,
                username=getattr(self.state.current_user, "username", ""),
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._after_movement("Perte de stock", pid)

    def _inventory(self) -> None:
        if not self._ensure_stock_permission():
            return
        pid = self._current_product_id()
        if not pid:
            warn(self, "Choisissez un produit.")
            return
        StockController.set_inventory(
            pid,
            self.quantity.value(),
            self.reason.text().strip() or "Inventaire",
            self.state.user_id,
            comment=self.comment.text(),
        )
        self._after_movement("Inventaire", pid)

    def _correction(self) -> None:
        if not self._ensure_stock_permission():
            return
        pid = self._current_product_id()
        if not pid:
            warn(self, "Choisissez un produit.")
            return
        motif = self.reason.text().strip()
        if not motif:
            warn(
                self,
                "Indiquez un motif pour l'ajustement "
                "(ex. : correction erreur de saisie).",
            )
            return
        StockController.correct(
            pid,
            self.quantity.value(),
            motif,
            self.state.user_id,
            comment=self.comment.text(),
        )
        self._after_movement("Ajustement / correction", pid)

    def _after_movement(self, label: str, pid: int) -> None:
        audit_service.log_action(
            label, "Stock", f"produit={pid}",
            self.state.user_id, getattr(self.state.current_user, "username", ""),
        )
        self.quantity.setValue(0)
        self.unit_cost.setValue(0)
        self.invoice_number.clear()
        self.reason.clear()
        self.comment.clear()
        self._reload_products()
        self._reload_history()
        self.state.notify_data_changed()
        info(self, f"{label} enregistré(e).")

    # --- Rafraîchissement --------------------------------------------------
    def refresh(self) -> None:
        self._reload_products()
        self._reload_suppliers()
        self._reload_history()

    def _reload_products(self) -> None:
        current = self.product_combo.currentData()
        self.product_combo.blockSignals(True)
        self.product_combo.clear()
        for product in ProductController.list(only_active=False):
            self.product_combo.addItem(
                f"{product.name} (stock: {format_quantity(product.quantity)})",
                product.id,
            )
        index = self.product_combo.findData(current)
        if index >= 0:
            self.product_combo.setCurrentIndex(index)
        self.product_combo.blockSignals(False)

    def _reload_suppliers(self) -> None:
        current = self.supplier_combo.currentData()
        self.supplier_combo.blockSignals(True)
        self.supplier_combo.clear()
        self.supplier_combo.addItem("— Aucun —", None)
        for supplier in SupplierController.list():
            self.supplier_combo.addItem(supplier.name, supplier.id)
        index = self.supplier_combo.findData(current)
        if index >= 0:
            self.supplier_combo.setCurrentIndex(index)
        self.supplier_combo.blockSignals(False)

    def _reload_history(self) -> None:
        movements = StockController.history(limit=self.HISTORY_LIMIT)
        self.history_note.setText(
            f"Historique limité aux {self.HISTORY_LIMIT} derniers mouvements."
            if len(movements) == self.HISTORY_LIMIT
            else ""
        )
        self.history_table.setRowCount(len(movements))
        for row, movement in enumerate(movements):
            product_name = movement.product.name if movement.product else "—"
            signed = movement.signed_quantity
            qty_text = (
                f"+{format_quantity(signed)}"
                if signed > 0
                else format_quantity(signed)
            )
            values = [
                format_datetime(movement.date),
                movement.user_label,
                product_name,
                movement.movement_type,
                qty_text,
                format_quantity(movement.quantity_after),
                movement.supplier_name or "—",
                movement.invoice_number or "—",
                movement.reason or "—",
                movement.comment or "—",
            ]
            for col, value in enumerate(values):
                self.history_table.setItem(row, col, QTableWidgetItem(value))
