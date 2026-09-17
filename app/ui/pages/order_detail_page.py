"""Détail commande plein écran — Maquis Caisse PC."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.models.open_order import STATUS_OPEN, STATUS_SERVED, STATUS_UNPAID
from app.services import permissions as perms, settings_service
from app.services.maquis_kitchen import print_kitchen_for_order
from app.services.order_status_labels import label_for_status
from app.ui.widgets.helpers import confirm
from app.services.order_checkout_service import checkout_open_order
from app.services.order_service import OrderService
from app.ui.dialogs.free_amount_dialog import FreeAmountDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import info, warn
from app.ui.widgets.pos_catalog_panel import PosCatalogPanel
from app.utils.helpers import format_money, format_quantity

_ACTIVE = (STATUS_OPEN, STATUS_SERVED, STATUS_UNPAID)


class OrderDetailPage(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.order_id: Optional[int] = None
        self._back: Optional[Callable[[], None]] = None
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        top = QVBoxLayout()
        back_row = QHBoxLayout()
        self.back_btn = QPushButton(t("← Retour"))
        self.back_btn.clicked.connect(self._go_back)
        back_row.addWidget(self.back_btn)
        back_row.addStretch()
        top.addLayout(back_row)
        self.catalog = PosCatalogPanel(self, show_pos_title=False)
        self.catalog.product_chosen.connect(self._on_product)
        top.addWidget(self.catalog, 1)
        root.addLayout(top, 5)
        right = QWidget()
        rlay = QVBoxLayout(right)
        self.header = QLabel("")
        self.header.setObjectName("PageTitle")
        rlay.addWidget(self.header)
        self.lines = QTableWidget(0, 5)
        self.lines.setHorizontalHeaderLabels(
            [t("Produit"), t("Qté"), t("Prix U."), t("Total"), ""]
        )
        self.lines.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        rlay.addWidget(self.lines, 1)
        self.total_label = QLabel("")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total_label.setStyleSheet("font-size: 22px; font-weight: 800;")
        rlay.addWidget(self.total_label)
        actions = QHBoxLayout()
        self.kitchen_btn = QPushButton(t("Bon serveur"))
        self.kitchen_btn.clicked.connect(self._print_kitchen)
        self.served_btn = QPushButton(t("Marquer servie"))
        self.served_btn.clicked.connect(self._mark_served)
        self.pay_btn = QPushButton(t("Marquer payée"))
        self.pay_btn.setObjectName("MaquisEncaisser")
        self.pay_btn.clicked.connect(self._pay)
        self.cancel_btn = QPushButton(t("Annuler"))
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.clicked.connect(self._cancel_order)
        self.edit_btn = QPushButton(t("Modifier"))
        self.edit_btn.clicked.connect(self._toggle_edit)
        self.save_edit_btn = QPushButton(t("Enregistrer"))
        self.save_edit_btn.setObjectName("Primary")
        self.save_edit_btn.clicked.connect(self._save_edits)
        self.save_edit_btn.setVisible(False)
        actions.addWidget(self.kitchen_btn)
        actions.addWidget(self.served_btn)
        actions.addStretch()
        actions.addWidget(self.edit_btn)
        actions.addWidget(self.save_edit_btn)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.pay_btn)
        self._editing = False
        self._edit_qty: dict[int, QDoubleSpinBox] = {}
        rlay.addLayout(actions)
        root.addWidget(right, 4)

    def set_back_handler(self, handler: Callable[[], None]) -> None:
        self._back = handler

    def load(self, order_id: int) -> None:
        self.order_id = order_id
        self.catalog.refresh()
        self._reload_lines()

    def _go_back(self) -> None:
        if self._back:
            self._back()

    def _reload_lines(self) -> None:
        if not self.order_id:
            return
        order = OrderService.get(self.order_id)
        if not order:
            return
        table_name = order.table_label or "—"
        if getattr(order, "table", None) is not None:
            table_name = order.table.display_name
        waitress = order.waitress_name or "—"
        self.header.setText(
            f"{order.public_id} · {table_name} · {waitress} · {label_for_status(order.status)}"
        )
        currency = settings_service.get_currency()
        open_order = order.status in _ACTIVE
        self._edit_qty.clear()
        self.pay_btn.setText(
            t("Encaisser")
            if order.status in (STATUS_UNPAID, STATUS_SERVED)
            else t("Marquer payée")
        )
        is_admin = getattr(self.state.current_user, "role", "") == perms.ROLE_ADMIN
        self.cancel_btn.setVisible(open_order and is_admin and not self._editing)
        self.edit_btn.setVisible(open_order and is_admin and not self._editing)
        self.save_edit_btn.setVisible(open_order and is_admin and self._editing)
        self.pay_btn.setVisible(open_order and not self._editing)
        self.served_btn.setVisible(
            open_order and order.status == STATUS_OPEN and not self._editing
        )
        self.catalog.setEnabled(open_order and not self._editing)
        items = list(order.items or [])
        self.lines.setRowCount(len(items))
        for row, it in enumerate(items):
            self.lines.setItem(row, 0, QTableWidgetItem(it.product_name or ""))
            self.lines.setItem(
                row, 1, QTableWidgetItem(format_quantity(float(it.quantity or 0)))
            )
            self.lines.setItem(
                row,
                2,
                QTableWidgetItem(format_money(float(it.unit_price or 0), currency)),
            )
            self.lines.setItem(
                row,
                3,
                QTableWidgetItem(format_money(float(it.line_total or 0), currency)),
            )
            if open_order and self._editing and is_admin:
                spin = QDoubleSpinBox()
                spin.setRange(0, 9999)
                spin.setDecimals(3)
                spin.setValue(float(it.quantity or 0))
                self._edit_qty[it.id] = spin
                self.lines.setCellWidget(row, 1, spin)
            elif open_order and not self._editing:
                del_btn = QPushButton("✕")
                del_btn.setObjectName("Danger")
                iid = it.id
                del_btn.clicked.connect(lambda _=False, lid=iid: self._remove_line(lid))
                self.lines.setCellWidget(row, 4, del_btn)
        total_txt = f"{t('Total')} : {format_money(float(order.total or 0), currency)}"
        remaining = float(order.remaining_amount)
        if order.status == STATUS_UNPAID and remaining > 0.009:
            total_txt += f"\n{t('Reste à payer')} : {format_money(remaining, currency)}"
        self.total_label.setText(total_txt)

    def _pay(self) -> None:
        if self.order_id and checkout_open_order(self.order_id, self.state, self):
            self._go_back()

    def _mark_served(self) -> None:
        if not self.order_id:
            return
        try:
            OrderService.mark_served(self.order_id)
            self.state.notify_data_changed()
            self._reload_lines()
            info(self, t("Commande marquée comme servie."), t("Servie"))
        except Exception as exc:
            warn(self, str(exc))

    def _toggle_edit(self) -> None:
        if getattr(self.state.current_user, "role", "") != perms.ROLE_ADMIN:
            warn(self, t("Seul l'administrateur peut modifier une commande."))
            return
        self._editing = not self._editing
        self._edit_qty.clear()
        self._reload_lines()

    def _save_edits(self) -> None:
        if not self.order_id:
            return
        order = OrderService.get(self.order_id)
        if not order:
            return
        lines = []
        for it in order.items or []:
            spin = self._edit_qty.get(it.id)
            qty = float(spin.value()) if spin else float(it.quantity or 0)
            if qty <= 0:
                continue
            lines.append(
                {
                    "product_id": it.product_id,
                    "product_name": it.product_name,
                    "quantity": qty,
                    "unit_price": float(it.unit_price or 0),
                }
            )
        if not lines:
            warn(self, t("La commande ne peut pas être vide."))
            return
        try:
            OrderService.replace_items(self.order_id, lines)
            self._editing = False
            self._edit_qty.clear()
            self._reload_lines()
            self.state.notify_data_changed()
            info(self, t("Commande mise à jour."))
        except Exception as exc:
            warn(self, str(exc))

    def _cancel_order(self) -> None:
        if not self.order_id:
            return
        if not confirm(self, t("Annuler cette commande ?"), t("Commande")):
            return
        try:
            OrderService.cancel(self.order_id)
            self.state.notify_data_changed()
            self._go_back()
        except Exception as exc:
            warn(self, str(exc))

    def _remove_line(self, item_id: int) -> None:
        try:
            OrderService.remove_item(item_id)
            self._reload_lines()
            self.state.notify_data_changed()
        except Exception as exc:
            warn(self, str(exc))

    def _on_product(self, product) -> None:
        if not self.order_id:
            return
        if getattr(product, "free_amount_sale", False):
            self._add_free_amount(product)
            return
        from app.ui.dialogs.quantity_pad_dialog import QuantityPadDialog

        dlg = QuantityPadDialog(product.name, parent=self)
        if not dlg.exec() or dlg.quantity <= 0:
            return
        try:
            OrderService.add_item(
                self.order_id,
                product_id=product.id,
                product_name=product.name,
                quantity=float(dlg.quantity),
                unit_price=float(product.sale_price or 0),
            )
            self._reload_lines()
            self.state.notify_data_changed()
        except Exception as exc:
            warn(self, str(exc))

    def _add_free_amount(self, product) -> None:
        sale_price = float(product.sale_price or 0)
        if sale_price <= 0:
            warn(self, f"« {product.name} » : prix de référence requis.")
            return
        dialog = FreeAmountDialog(product.name, sale_price, parent=self)
        if not dialog.exec() or not dialog.amount:
            return
        amount = float(dialog.amount)
        qty = amount / sale_price
        currency = settings_service.get_currency()
        label = f"{product.name} — {format_money(amount, currency)}"
        try:
            OrderService.add_item(
                self.order_id,
                product_id=product.id,
                product_name=label,
                quantity=qty,
                unit_price=sale_price,
            )
            self._reload_lines()
            self.state.notify_data_changed()
        except Exception as exc:
            warn(self, str(exc))

    def _print_kitchen(self) -> None:
        if not self.order_id:
            return
        user = getattr(self.state.current_user, "username", "") or ""
        ok, msg = print_kitchen_for_order(self.order_id, cashier_name=user)
        if ok:
            info(self, msg, t("Bon serveur"))
        else:
            warn(self, msg, t("Bon serveur"))
