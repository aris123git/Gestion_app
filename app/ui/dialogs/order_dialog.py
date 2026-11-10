"""Commande client : une seule saisie crée le bon d'enlèvement (signé du fournisseur), l'achat et la vente."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QVBoxLayout,
)

from app.controllers.product_controller import ProductController
from app.controllers.sale_controller import BelowMinPriceError, InsufficientStockError
from app.controllers.supplier_controller import SupplierController
from app.i18n import t
from app.services import audit_service, pickup_service as ps, settings_service
from app.ui.widgets.client_search import ClientSearchField
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import warn
from app.ui.widgets.money_spin import MoneySpinBox
from app.utils.helpers import format_money


class OrderDialog(QDialog):
    COLS = ("Produit", "Quantité", "Prix d'achat", "Prix de vente", "Total")

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.result_sale_id: int | None = None
        self.setWindowTitle(t("Commande client"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=760, min_height=560, preferred_width=900, preferred_height=660)
        self._products = [p for p in ProductController.list() if getattr(p, "active", True)]
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.client = ClientSearchField(placeholder=t("Client de la commande (nom ou téléphone)…"))
        self.supplier = QComboBox()
        for s in SupplierController.list():
            self.supplier.addItem(s.name, s.id)
        self.driver, self.truck, self.reference = QLineEdit(), QLineEdit(), QLineEdit()
        form.addRow(t("Client"), self.client)
        form.addRow(t("Fournisseur (signe le bon d'enlèvement)"), self.supplier)
        form.addRow(t("Chauffeur"), self.driver)
        form.addRow(t("N° du camion"), self.truck)
        form.addRow(t("Référence"), self.reference)
        root.addLayout(form)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([t(c) for c in self.COLS])
        self.table.setColumnWidth(0, 280)
        root.addWidget(self.table, 1)
        self._rows: list = []
        row = QHBoxLayout()
        add = QPushButton(t("+ Ajouter un produit"))
        add.clicked.connect(lambda: self._add_row())
        rm = QPushButton(t("Retirer la ligne"))
        rm.clicked.connect(self._remove_row)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch()
        root.addLayout(row)
        self.credit = QCheckBox(t("Vente à crédit (dette du client)"))
        root.addWidget(self.credit)
        self.total = QLabel()
        self.total.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.total)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(t("Enregistrer la commande"))
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self._add_row()

    def _add_row(self) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        combo = QComboBox()
        for p in self._products:
            combo.addItem(p.name, p.id)
        combo.setCurrentIndex(-1)
        qty = QDoubleSpinBox()
        qty.setRange(0, 1_000_000_000)
        qty.setDecimals(3)
        cost, price = MoneySpinBox(), MoneySpinBox()
        for s in (cost, price):
            s.setRange(0, 1_000_000_000)
        total = QLabel("0")
        total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for c, w in enumerate((combo, qty, cost, price, total)):
            self.table.setCellWidget(r, c, w)
        combo.currentIndexChanged.connect(lambda _i, c=combo, co=cost, pr=price: self._fill(c, co, pr))
        qty.valueChanged.connect(self._recalc)
        price.valueChanged.connect(self._recalc)
        self._rows.append((combo, qty, cost, price, total))

    def _fill(self, combo, cost, price) -> None:
        p = next((x for x in self._products if x.id == combo.currentData()), None)
        if p is not None:
            cost.setValue(float(getattr(p, "purchase_price", 0) or 0))
            price.setValue(float(getattr(p, "sale_price", 0) or 0))
        self._recalc()

    def _remove_row(self) -> None:
        r = self.table.currentRow()
        if r >= 0 and len(self._rows) > 1:
            self.table.removeRow(r)
            self._rows.pop(r)
            self._recalc()

    def _lines(self) -> list:
        return [ps.OrderLine(c.currentData(), q.value(), co.value(), pr.value()) for c, q, co, pr, _t in self._rows if c.currentData() and q.value() > 0]

    def _recalc(self, *_a) -> None:
        for c, q, co, pr, tot in self._rows:
            tot.setText(f"{q.value() * pr.value():,.0f}".replace(",", " "))
        cur = settings_service.get_shop_info().currency or "FCFA"
        sale = sum(l.quantity * l.unit_price for l in self._lines())
        buy = sum(l.quantity * l.unit_cost for l in self._lines())
        self.total.setText(f"<b>{t('Total à facturer')} : {format_money(sale, cur)}</b> "
                           f"<span style='color:#64748b'>({t('achat fournisseur')} {format_money(buy, cur)})</span>")

    def _accept(self) -> None:
        user_id = self.state.user_id
        username = getattr(self.state.current_user, "username", "")
        try:
            result = ps.place_order(self.client.client_id, self.supplier.currentData(), self._lines(), on_credit=self.credit.isChecked(),
                                    driver=self.driver.text().strip(), truck=self.truck.text().strip(), reference=self.reference.text().strip(),
                                    user_id=user_id, username=username)
        except (ValueError, BelowMinPriceError) as exc:
            warn(self, str(exc), t("Commande impossible"))
            return
        except InsufficientStockError as exc:
            warn(self, str(exc), t("Stock insuffisant"))
            return
        audit_service.log_action("Commande client", "Sale", f"{result.ticket_number} bon={result.pickup_number}", user_id, username)
        self.result_sale_id = result.sale_id
        self.accept()
