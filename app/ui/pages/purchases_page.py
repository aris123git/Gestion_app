"""Page des achats / réceptions fournisseurs."""

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
    QVBoxLayout,
    QWidget,
)

from app.controllers.product_controller import ProductController
from app.controllers.supplier_controller import SupplierController
from app.services import permissions as perms, settings_service
from app.services.purchase_service import PurchaseLine, PurchaseService
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.utils.helpers import format_datetime, format_money, format_quantity


class PurchasesPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._lines: list[PurchaseLine] = []
        self._purchase_ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(page_title("Achats / Réceptions"))

        form_w = QWidget()
        form = QFormLayout(form_w)
        self.supplier = QComboBox()
        self.invoice = QLineEdit()
        self.product = QComboBox()
        self.qty = QDoubleSpinBox()
        self.qty.setRange(0.001, 10_000_000)
        self.qty.setDecimals(3)
        self.qty.setValue(1)
        self.cost = QDoubleSpinBox()
        self.cost.setRange(0, 1_000_000_000)
        self.paid = QDoubleSpinBox()
        self.paid.setRange(0, 1_000_000_000)
        self.note = QLineEdit()
        form.addRow("Fournisseur", self.supplier)
        form.addRow("N° facture", self.invoice)
        form.addRow("Produit", self.product)
        form.addRow("Quantité", self.qty)
        form.addRow("Coût unitaire", self.cost)
        form.addRow("Montant payé", self.paid)
        form.addRow("Note", self.note)
        layout.addWidget(make_card(form_w))

        btns = QHBoxLayout()
        add_line = QPushButton("Ajouter la ligne")
        add_line.clicked.connect(self._add_line)
        save = QPushButton("Enregistrer l'achat")
        save.setObjectName("Success")
        save.clicked.connect(self._save)
        btns.addWidget(add_line)
        btns.addStretch()
        btns.addWidget(save)
        layout.addLayout(btns)

        self.lines_table = QTableWidget(0, 4)
        self.lines_table.setHorizontalHeaderLabels(
            ["Produit", "Qté", "Coût U.", "Total"]
        )
        self.lines_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.lines_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.lines_table)

        self.history = QTableWidget(0, 6)
        self.history.setHorizontalHeaderLabels(
            ["Date", "Fournisseur", "Facture", "Total", "Payé", "Statut"]
        )
        self.history.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.history.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.history)

        history_actions = QHBoxLayout()
        history_actions.addStretch()
        self.cancel_purchase_button = QPushButton("Annuler l'achat sélectionné")
        self.cancel_purchase_button.setObjectName("Danger")
        self.cancel_purchase_button.clicked.connect(self._cancel_selected_purchase)
        history_actions.addWidget(self.cancel_purchase_button)
        layout.addLayout(history_actions)
        self._apply_permissions()

    def _apply_permissions(self) -> None:
        self.cancel_purchase_button.setVisible(self.state.can(perms.MANAGE_PURCHASES))

    def refresh(self) -> None:
        self._apply_permissions()
        self.supplier.blockSignals(True)
        self.supplier.clear()
        self.supplier.addItem("— Aucun —", None)
        for s in SupplierController.list():
            self.supplier.addItem(s.name, s.id)
        self.supplier.blockSignals(False)

        self._product_costs: dict[int, float] = {}
        self.product.blockSignals(True)
        self.product.clear()
        for p in ProductController.list():
            self.product.addItem(p.name, p.id)
            self._product_costs[p.id] = float(p.purchase_price)
        self.product.blockSignals(False)
        self._reload_history()

    def _add_line(self) -> None:
        pid = self.product.currentData()
        if not pid or self.qty.value() <= 0:
            warn(self, "Choisissez un produit et une quantité.")
            return
        name = self.product.currentText()
        cost = self.cost.value()
        if cost <= 0:
            cost = self._product_costs.get(pid, 0.0)
        line = PurchaseLine(pid, name, self.qty.value(), cost)
        self._lines.append(line)
        self._render_lines()

    def _render_lines(self) -> None:
        currency = settings_service.get_currency()
        self.lines_table.setRowCount(len(self._lines))
        for row, line in enumerate(self._lines):
            self.lines_table.setItem(row, 0, QTableWidgetItem(line.name))
            self.lines_table.setItem(row, 1, QTableWidgetItem(format_quantity(line.quantity)))
            self.lines_table.setItem(row, 2, QTableWidgetItem(format_money(line.unit_cost, currency)))
            self.lines_table.setItem(row, 3, QTableWidgetItem(format_money(line.total, currency)))

    def _save(self) -> None:
        if not self.state.can(perms.MANAGE_PURCHASES):
            warn(self, "Autorisation insuffisante.")
            return
        if not self._lines:
            warn(self, "Ajoutez au moins une ligne.")
            return
        try:
            purchase = PurchaseService.create(
                list(self._lines),
                supplier_id=self.supplier.currentData(),
                invoice_number=self.invoice.text(),
                amount_paid=self.paid.value(),
                note=self.note.text(),
                user_id=self.state.user_id,
                username=getattr(self.state.current_user, "username", ""),
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._lines.clear()
        self._render_lines()
        self.invoice.clear()
        self.note.clear()
        self.paid.setValue(0)
        self._reload_history()
        self.state.notify_data_changed()
        info(self, f"Achat #{purchase.id} enregistré.")

    def _reload_history(self) -> None:
        currency = settings_service.get_currency()
        rows = PurchaseService.list(limit=100)
        self._purchase_ids = [p.id for p in rows]
        self.history.setRowCount(len(rows))
        for i, p in enumerate(rows):
            supplier = p.supplier.name if p.supplier else "—"
            self.history.setItem(i, 0, QTableWidgetItem(format_datetime(p.date)))
            self.history.setItem(i, 1, QTableWidgetItem(supplier))
            self.history.setItem(i, 2, QTableWidgetItem(p.invoice_number or "—"))
            self.history.setItem(i, 3, QTableWidgetItem(format_money(p.total, currency)))
            self.history.setItem(i, 4, QTableWidgetItem(format_money(p.amount_paid, currency)))
            label = "Annulé" if p.status == "cancelled" else "Terminé"
            self.history.setItem(i, 5, QTableWidgetItem(label))

    def _cancel_selected_purchase(self) -> None:
        row = self.history.currentRow()
        if row < 0 or row >= len(self._purchase_ids):
            warn(self, "Sélectionnez un achat dans l'historique.")
            return
        if not self.state.can(perms.MANAGE_PURCHASES):
            warn(self, "Autorisation insuffisante.")
            return
        purchase_id = self._purchase_ids[row]
        if not confirm(
            self,
            f"Annuler l'achat #{purchase_id} ?\n\n"
            "Le stock reçu sera retiré et la dette fournisseur liée sera annulée "
            "si aucun remboursement n'existe.",
        ):
            return
        try:
            PurchaseService.cancel_purchase(
                purchase_id,
                user_id=self.state.user_id,
                username=getattr(self.state.current_user, "username", ""),
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._reload_history()
        self.refresh()
        self.state.notify_data_changed()
        info(self, f"Achat #{purchase_id} annulé.")
