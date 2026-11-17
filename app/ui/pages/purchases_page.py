"""Page des achats / réceptions fournisseurs : liste + détail, saisie dans une fenêtre."""
from __future__ import annotations

from datetime import datetime, time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.controllers.product_controller import ProductController
from app.controllers.supplier_controller import SupplierController
from app.i18n import t
from app.services import permissions as perms, settings_service
from app.services.purchase_service import PurchaseLine, PurchaseService
from app.services.supplier_debt_service import SupplierDebtService
from app.ui.state import AppState
from app.ui.widgets.batch import enable_multi, run_batch, selected_rows
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.ui.widgets.money_spin import MoneySpinBox
from app.ui.widgets.period_picker import PeriodPicker
from app.utils.helpers import format_datetime, format_money, format_quantity


def _table(headers: list[str]) -> QTableWidget:
    tb = QTableWidget(0, len(headers))
    tb.setHorizontalHeaderLabels([t(h) for h in headers])
    tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tb.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tb.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    tb.verticalHeader().setVisible(False)
    tb.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    return tb


def _cell(text: str, right: bool = False, color: str | None = None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    if right:
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if color:
        from PySide6.QtGui import QColor
        it.setForeground(QColor(color))
    return it


class PurchaseDialog(QDialog):
    """Nouvel achat : fournisseur, facture, lignes, montant payé."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t('Nouvel achat'))
        self.setMinimumWidth(680)
        self._lines: list[PurchaseLine] = []
        self._costs: dict[int, float] = {}
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.supplier = QComboBox()
        self.supplier.addItem(t('— Aucun —'), None)
        for s in SupplierController.list():
            self.supplier.addItem(s.name, s.id)
        self.invoice = QLineEdit()
        form.addRow(t('Fournisseur'), self.supplier)
        form.addRow(t('N° facture'), self.invoice)
        root.addLayout(form)
        add = QFormLayout()
        self.product = QComboBox()
        for p in ProductController.list():
            self.product.addItem(p.name, p.id)
            self._costs[p.id] = float(p.purchase_price)
        self.qty = QDoubleSpinBox()
        self.qty.setRange(0.001, 10000000)
        self.qty.setDecimals(3)
        self.qty.setValue(1)
        self.use_catalog_cost = QCheckBox(t("Utiliser le prix d'achat du produit"))
        self.use_catalog_cost.setChecked(True)
        self.cost = MoneySpinBox()
        self.cost.setRange(0, 1000000000)
        self.new_sale_price = MoneySpinBox()
        self.new_sale_price.setRange(0, 1000000000)
        self.new_sale_price.setDecimals(3)
        self.new_sale_price.setToolTip(t("Optionnel. Si de l'ancien stock reste, ce prix ne s'appliquera qu'après sa vente complète. 0 = ne pas changer."))
        self.use_catalog_cost.toggled.connect(self._on_product_changed)
        self.product.currentIndexChanged.connect(self._on_product_changed)
        add.addRow(t('Produit'), self.product)
        add.addRow(t('Quantité'), self.qty)
        add.addRow('', self.use_catalog_cost)
        add.addRow(t('Coût unitaire'), self.cost)
        add.addRow(t('Nouveau prix de vente (après ancien stock)'), self.new_sale_price)
        root.addWidget(make_card(self._wrap(add)))
        row = QHBoxLayout()
        b_add = QPushButton(t('+ Ajouter la ligne'))
        b_add.clicked.connect(self._add_line)
        b_rm = QPushButton(t('Retirer la ligne'))
        b_rm.clicked.connect(self._remove_line)
        self.total_label = QLabel()
        self.total_label.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(b_add)
        row.addWidget(b_rm)
        row.addStretch()
        row.addWidget(self.total_label)
        root.addLayout(row)
        self.lines_table = _table(['Produit', 'Qté', 'Coût U.', 'Total'])
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.lines_table.setMinimumHeight(160)
        root.addWidget(self.lines_table, 1)
        bottom = QFormLayout()
        self.paid = MoneySpinBox()
        self.paid.setRange(0, 1000000000)
        self.note = QLineEdit()
        bottom.addRow(t('Montant payé'), self.paid)
        bottom.addRow(t('Note'), self.note)
        root.addLayout(bottom)
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton(t('Annuler'))
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton(t("Enregistrer l'achat"))
        self.save_button.setObjectName('Success')
        self.save_button.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(self.save_button)
        root.addLayout(btns)
        self._on_product_changed()
        self._render()
        fit_dialog_to_screen(self)

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _on_product_changed(self, *_a) -> None:
        use = self.use_catalog_cost.isChecked()
        self.cost.setEnabled(not use)
        if use:
            self.cost.setValue(self._costs.get(self.product.currentData(), 0.0))

    def _add_line(self) -> None:
        pid = self.product.currentData()
        if not pid or self.qty.value() <= 0:
            warn(self, t('Choisissez un produit et une quantité.'))
            return
        cost = self.cost.value() or self._costs.get(pid, 0.0)
        self._lines.append(PurchaseLine(pid, self.product.currentText(), self.qty.value(), cost, self.new_sale_price.value() or None))
        self._render()

    def _remove_line(self) -> None:
        r = self.lines_table.currentRow()
        if 0 <= r < len(self._lines):
            del self._lines[r]
            self._render()

    def _render(self) -> None:
        cur = settings_service.get_currency()
        self.lines_table.setRowCount(len(self._lines))
        for r, ln in enumerate(self._lines):
            for c, v in enumerate([ln.name, format_quantity(ln.quantity), format_money(ln.unit_cost, cur), format_money(ln.total, cur)]):
                self.lines_table.setItem(r, c, _cell(v, c > 0))
        total = sum(ln.total for ln in self._lines)
        self.total_label.setText(f"<span style='font-size:15px'><b>{t('TOTAL')} ({len(self._lines)}) : {format_money(total, cur)}</b></span>")

    def _save(self) -> None:
        if not self._lines:
            warn(self, t('Ajoutez au moins une ligne.'))
            return
        self.accept()

    def values(self) -> dict:
        return dict(lines=list(self._lines), supplier_id=self.supplier.currentData(), invoice_number=self.invoice.text(),
                    amount_paid=self.paid.value(), note=self.note.text())


class PayDialog(QDialog):
    """Paiement (total ou partiel) du reste dû sur un achat."""

    def __init__(self, rest: float, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t('Payer le reste'))
        form = QFormLayout(self)
        self.amount = MoneySpinBox()
        self.amount.setRange(0, rest)
        self.amount.setValue(rest)
        self.method = QComboBox()
        self.method.addItems(['Espèces', 'Mobile Money', 'Virement', 'Chèque'])
        form.addRow(t('Montant'), self.amount)
        form.addRow(t('Mode de paiement'), self.method)
        row = QHBoxLayout()
        no = QPushButton(t('Annuler'))
        no.clicked.connect(self.reject)
        ok = QPushButton(t('Enregistrer'))
        ok.setObjectName('Success')
        ok.clicked.connect(self.accept)
        row.addWidget(no)
        row.addWidget(ok)
        form.addRow(row)


class PurchasesPage(QWidget):
    FILTERS = [('all', 'Tous'), ('due', 'À payer'), ('cancelled', 'Annulés')]

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._filter = 'all'
        self._rows: list = []
        self._debts: dict[int, tuple[int, float]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(page_title(t('Achats / Réceptions')))
        top.addStretch()
        self.picker = PeriodPicker()
        self.picker.mode.setCurrentIndex(self.picker.mode.findData('month'))
        self.picker.changed.connect(self.refresh)
        top.addWidget(self.picker)
        self.new_button = QPushButton(t('+ Nouvel achat'))
        self.new_button.setObjectName('Success')
        self.new_button.clicked.connect(self._new)
        top.addWidget(self.new_button)
        layout.addLayout(top)
        kp = QHBoxLayout()
        self.k_total, self.k_paid, self.k_due = QLabel(), QLabel(), QLabel()
        for k in (self.k_total, self.k_paid, self.k_due):
            k.setTextFormat(Qt.TextFormat.RichText)
            kp.addWidget(make_card(k), 1)
        layout.addLayout(kp)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('Rechercher fournisseur ou n° facture…'))
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.search, 1)
        self._chips = {}
        for key, label in self.FILTERS:
            b = QPushButton(t(label))
            b.setCheckable(True)
            b.setStyleSheet('QPushButton:checked { background: #2563eb; color: #ffffff; border-color: #2563eb; }')
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self._chips[key] = b
            bar.addWidget(b)
        layout.addLayout(bar)
        body = QHBoxLayout()
        self.history = _table(['Date', 'Fournisseur', 'Facture', 'Total', 'Reste'])
        self.history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        enable_multi(self.history)
        self.history.currentCellChanged.connect(lambda *_: self._show())
        body.addWidget(self.history, 3)
        side = QVBoxLayout()
        self.d_head = QLabel(t('Sélectionnez un achat.'))
        self.d_head.setTextFormat(Qt.TextFormat.RichText)
        self.d_head.setWordWrap(True)
        side.addWidget(self.d_head)
        self.d_lines = _table(['Produit', 'Qté', 'Coût U.', 'Total'])
        self.d_lines.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        side.addWidget(self.d_lines, 1)
        self.d_total = QLabel()
        self.d_total.setTextFormat(Qt.TextFormat.RichText)
        self.d_total.setAlignment(Qt.AlignmentFlag.AlignRight)
        side.addWidget(self.d_total)
        btns = QHBoxLayout()
        self.pay_button = QPushButton(t('Payer le reste'))
        self.pay_button.setObjectName('Primary')
        self.pay_button.clicked.connect(self._pay)
        self.cancel_purchase_button = QPushButton(t("Annuler l'achat"))
        self.cancel_purchase_button.setObjectName('DangerOutline')
        self.cancel_purchase_button.clicked.connect(self._cancel_selected_purchase)
        btns.addWidget(self.pay_button)
        btns.addWidget(self.cancel_purchase_button)
        side.addLayout(btns)
        body.addLayout(side, 2)
        layout.addLayout(body, 1)
        self._chips['all'].setChecked(True)
        self._apply_permissions()

    # ---- helpers --------------------------------------------------------------------------
    @property
    def manual(self):          # la saisie manuelle disparaît en mode Entreprise (tout passe par la commande client)
        return self.new_button

    def _user(self):
        return self.state.user_id, getattr(self.state.current_user, 'username', '')

    def _apply_permissions(self) -> None:
        from app.services.business_mode import is_enterprise
        can = self.state.can(perms.MANAGE_PURCHASES)
        self.new_button.setVisible(not is_enterprise())
        self.new_button.setEnabled(can)
        self.cancel_purchase_button.setVisible(can)
        self.pay_button.setVisible(can)

    def _set_filter(self, key: str) -> None:
        self._filter = key
        for k, b in self._chips.items():
            b.setChecked(k == key)
        self.refresh()

    def _remaining(self, purchase_id: int) -> float:
        return self._debts.get(purchase_id, (0, 0.0))[1]

    # ---- affichage ------------------------------------------------------------------------
    def refresh(self, *_a) -> None:
        self._apply_permissions()
        cur = settings_service.get_currency()
        d0, d1 = self.picker.period()
        start, end = datetime.combine(d0, time.min), datetime.combine(d1, time.max)
        self._debts = {}
        for d in SupplierDebtService.list_debts(only_active=True, limit=100000):
            if d.purchase_id:
                self._debts[d.purchase_id] = (d.id, float(d.amount_remaining))
        needle = self.search.text().strip().lower()
        rows = []
        for p in PurchaseService.list(limit=5000):
            if not (start <= p.date <= end):
                continue
            name = p.supplier.name if p.supplier else ''
            if needle and needle not in name.lower() and needle not in (p.invoice_number or '').lower():
                continue
            cancelled = p.status == 'cancelled'
            if self._filter == 'cancelled' and not cancelled:
                continue
            if self._filter == 'due' and (cancelled or self._remaining(p.id) <= 0):
                continue
            rows.append(p)
        self._rows = rows
        live = [p for p in rows if p.status != 'cancelled']
        total = sum(float(p.total) for p in live)
        due = sum(self._remaining(p.id) for p in live)
        self.k_total.setText(f"<span style='color:#64748b'>{t('Achats de la période')}</span><br><b style='font-size:18px'>{format_money(total, cur)}</b>")
        self.k_paid.setText(f"<span style='color:#64748b'>{t('Payé')}</span><br><b style='font-size:18px;color:#15803d'>{format_money(total - due, cur)}</b>")
        self.k_due.setText(f"<span style='color:#64748b'>{t('Reste à payer aux fournisseurs')}</span><br><b style='font-size:18px;color:#b91c1c'>{format_money(due, cur)}</b>")
        self.history.blockSignals(True)
        self.history.setRowCount(len(rows))
        for r, p in enumerate(rows):
            rest = self._remaining(p.id)
            if p.status == 'cancelled':
                rest_cell = _cell(t('annulé'), True, '#64748b')
            elif rest > 0:
                rest_cell = _cell(format_money(rest, cur), True, '#b91c1c')
            else:
                rest_cell = _cell(t('soldé'), True, '#15803d')
            first = _cell(format_datetime(p.date))
            first.setData(Qt.ItemDataRole.UserRole, p.id)
            vals = [first, _cell(p.supplier.name if p.supplier else '—'), _cell(p.invoice_number or '—'), _cell(format_money(p.total, cur), True), rest_cell]
            for c, it in enumerate(vals):
                self.history.setItem(r, c, it)
        self.history.blockSignals(False)
        self._show()

    def _selected(self):
        r = self.history.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def _show(self) -> None:
        p = self._selected()
        self.pay_button.setEnabled(False)
        self.cancel_purchase_button.setEnabled(False)
        if not p:
            self.d_head.setText(t('Sélectionnez un achat.'))
            self.d_lines.setRowCount(0)
            self.d_total.setText('')
            return
        cur = settings_service.get_currency()
        full = PurchaseService.get(p.id)
        status = t('Annulé') if p.status == 'cancelled' else t('Terminé')
        self.d_head.setText(f"<b style='font-size:15px'>{p.supplier.name if p.supplier else '—'} · {p.invoice_number or '—'}</b><br>"
                            f"<span style='color:#64748b'>{format_datetime(p.date)} · {status}</span>")
        items = list(full.items) if full else []
        self.d_lines.setRowCount(len(items))
        for r, it in enumerate(items):
            for c, v in enumerate([it.product_name, format_quantity(it.quantity), format_money(it.unit_cost, cur), format_money(it.line_total, cur)]):
                self.d_lines.setItem(r, c, _cell(v, c > 0))
        rest = self._remaining(p.id)
        self.d_total.setText(f"{t('Total')} <b>{format_money(p.total, cur)}</b> · {t('Reste')} <b style='color:{'#b91c1c' if rest > 0 else '#15803d'}'>{format_money(rest, cur)}</b>")
        live = p.status != 'cancelled'
        self.pay_button.setEnabled(live and rest > 0)
        self.cancel_purchase_button.setEnabled(live)

    # ---- actions --------------------------------------------------------------------------
    def _new(self) -> None:
        if not self.state.can(perms.MANAGE_PURCHASES):
            warn(self, t('Autorisation insuffisante.'))
            return
        dlg = PurchaseDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        try:
            purchase = PurchaseService.create(v['lines'], supplier_id=v['supplier_id'], invoice_number=v['invoice_number'], amount_paid=v['amount_paid'], note=v['note'], user_id=self.state.user_id, username=self._user()[1])
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        self.state.notify_data_changed()
        info(self, f'Achat #{purchase.id} enregistré.')

    def _pay(self) -> None:
        p = self._selected()
        if not p or not self.state.can(perms.MANAGE_PURCHASES):
            return
        debt_id, rest = self._debts.get(p.id, (0, 0.0))
        if rest <= 0:
            return
        dlg = PayDialog(rest, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            SupplierDebtService.pay_debt(debt_id, dlg.amount.value(), payment_method=dlg.method.currentText(), user_id=self.state.user_id, username=self._user()[1])
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        self.state.notify_data_changed()
        info(self, t('Remboursement fournisseur enregistré.'))

    def _cancel_selected_purchase(self) -> None:
        rows = selected_rows(self.history)
        if len(rows) > 1 and self.state.can(perms.MANAGE_PURCHASES):
            items = [(self._rows[r].id, f"#{self._rows[r].id}") for r in rows if self._rows[r].status != 'cancelled']
            user = self._user()[1]
            if run_batch(self, t("Annuler {n} achats ?\n\nLe stock reçu sera retiré. Un achat déjà remboursé sera signalé et conservé."), items,
                         lambda pid: PurchaseService.cancel_purchase(pid, user_id=self.state.user_id, username=user), t("achat(s) annulé(s)")):
                self.refresh()
                self.state.notify_data_changed()
            return
        p = self._selected()
        if not p:
            warn(self, t("Sélectionnez un achat dans l'historique."))
            return
        if not self.state.can(perms.MANAGE_PURCHASES):
            warn(self, t('Autorisation insuffisante.'))
            return
        if not confirm(self, f"Annuler l'achat #{p.id} ?\n\nLe stock reçu sera retiré et la dette fournisseur liée sera annulée si aucun remboursement n'existe."):
            return
        try:
            PurchaseService.cancel_purchase(p.id, user_id=self.state.user_id, username=self._user()[1])
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        self.state.notify_data_changed()
        info(self, f"Achat #{p.id} annulé.")
