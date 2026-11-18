"""Page de gestion des fournisseurs (CRUD, recherche)."""
from __future__ import annotations
from app.i18n import t
from app.ui.widgets.batch import enable_multi, run_batch, selected_rows
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMenu, QAbstractItemView, QHBoxLayout, QHeaderView, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app.controllers.supplier_controller import SupplierController
from app.services import permissions as perms, settings_service
from app.services.supplier_debt_service import SupplierDebtService
from app.ui.dialogs.contact_dialog import ContactDialog
from app.ui.dialogs.debt_payment_dialog import DebtPaymentDialog
from app.ui.responsive import LayoutProfile, SUPPLIER_COLUMNS, TableColumnController
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.utils.helpers import format_money

class SuppliersPage(QWidget):
    HEADERS = ['Nom', 'Téléphone', 'Dette']

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._ids: list[int] = []
        self._filter = 'all'
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(page_title(t('Fournisseurs')))
        header.addStretch()
        add = QPushButton(t('+ Nouveau fournisseur'))
        add.setObjectName('Primary')
        add.clicked.connect(self._add)
        header.addWidget(add)
        layout.addLayout(header)
        kp = QHBoxLayout()
        self.k_count, self.k_due, self.k_order = QLabel(), QLabel(), QLabel()
        for k in (self.k_count, self.k_due, self.k_order):
            k.setTextFormat(Qt.TextFormat.RichText)
            k.setMinimumHeight(44)
            kp.addWidget(make_card(k), 1)
        layout.addLayout(kp)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('Rechercher (nom, téléphone)…'))
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.search, 1)
        self._chips = {}
        for key, label in (('all', 'Tous'), ('due', 'À payer')):
            chip = QPushButton(t(label))
            chip.setCheckable(True)
            chip.setStyleSheet('QPushButton:checked { background: #2563eb; color: #ffffff; border-color: #2563eb; }')
            chip.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self._chips[key] = chip
            bar.addWidget(chip)
        layout.addLayout(bar)
        body = QHBoxLayout()
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([t(h) for h in self.HEADERS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        enable_multi(self.table)
        self.table.doubleClicked.connect(self._edit)
        self.table.currentCellChanged.connect(lambda *_: self._show())
        body.addWidget(self.table, 3)
        side = QVBoxLayout()
        self.d_head = QLabel(t('Sélectionnez un fournisseur.'))
        self.d_head.setTextFormat(Qt.TextFormat.RichText)
        self.d_head.setWordWrap(True)
        side.addWidget(self.d_head)
        self.d_info = QLabel()
        self.d_info.setTextFormat(Qt.TextFormat.RichText)
        side.addWidget(self.d_info)
        self.d_buys = QLabel()
        self.d_buys.setTextFormat(Qt.TextFormat.RichText)
        self.d_buys.setWordWrap(True)
        side.addWidget(self.d_buys)
        side.addStretch(1)
        self.buttons = {}
        r1, r2 = QHBoxLayout(), QHBoxLayout()
        for lay, key, label, handler, obj in ((r1, 'wa', 'WhatsApp / Commander', self._whatsapp, 'Primary'), (r1, 'settle', 'Régler dette', self._settle_debt, 'Success'),
                                              (r2, 'edit', 'Modifier', self._edit, '')):
            b = QPushButton(t(label))
            if obj:
                b.setObjectName(obj)
            b.clicked.connect(handler)
            self.buttons[key] = b
            lay.addWidget(b)
        more = QPushButton(t('Plus ▾'))
        menu = QMenu(more)
        menu.addAction(t('Supprimer'), self._delete)
        more.setMenu(menu)
        self.buttons['more'] = more
        r2.addWidget(more)
        side.addLayout(r1)
        side.addLayout(r2)
        body.addLayout(side, 2)
        layout.addLayout(body, 1)
        self._chips['all'].setChecked(True)

    def _set_filter(self, key: str) -> None:
        self._filter = key
        for k, c in self._chips.items():
            c.setChecked(k == key)
        self.refresh()

    def refresh(self, *_a) -> None:
        from app.services import order_message
        currency = settings_service.get_currency()
        everyone = SupplierController.list('')
        debts = {}
        for d in SupplierDebtService.list_debts(only_active=True, limit=20000):
            debts[d.supplier_id] = debts.get(d.supplier_id, 0.0) + float(d.amount_remaining or 0)
        self.k_count.setText(f"<span style='color:#64748b'>{t('Fournisseurs')}</span><br><b style='font-size:18px'>{len(everyone)}</b>")
        self.k_due.setText(f"<span style='color:#64748b'>{t('Dettes à payer')}</span><br><b style='font-size:18px;color:#b91c1c'>{format_money(sum(debts.values()), currency)}</b> <span style='color:#64748b'>({len(debts)})</span>")
        self.k_order.setText(f"<span style='color:#64748b'>{t('Produits à commander')}</span><br><b style='font-size:18px'>{len(order_message.products_to_order())}</b>")
        suppliers = SupplierController.list(self.search.text().strip())
        if self._filter == 'due':
            suppliers = [s for s in suppliers if debts.get(s.id, 0) > 0]
        keep = self._selected_id()
        self._ids = [s.id for s in suppliers]
        self._debts = debts
        self.table.blockSignals(True)
        self.table.setRowCount(len(suppliers))
        for row, supplier in enumerate(suppliers):
            self.table.setItem(row, 0, QTableWidgetItem(supplier.name))
            self.table.setItem(row, 1, QTableWidgetItem(supplier.phone))
            owed = debts.get(supplier.id, 0.0)
            item = QTableWidgetItem(format_money(owed, currency) if owed > 0 else '—')
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setForeground(Qt.GlobalColor.red if owed > 0 else Qt.GlobalColor.gray)
            self.table.setItem(row, 2, item)
        self.table.blockSignals(False)
        if keep in self._ids:
            self.table.setCurrentCell(self._ids.index(keep), 0)
        self._show()

    def _show(self) -> None:
        from app.controllers.product_controller import ProductController
        from app.services import order_message
        from app.services.purchase_service import PurchaseService
        sid = self._selected_id()
        for b in self.buttons.values():
            b.setEnabled(bool(sid))
        if not sid:
            self.d_head.setText(t('Sélectionnez un fournisseur.'))
            self.d_info.setText('')
            self.d_buys.setText('')
            return
        supplier = SupplierController.get(sid)
        if not supplier:
            return
        cur = settings_service.get_currency()
        owed = self._debts.get(sid, 0.0)
        extra = ' · '.join(x for x in (supplier.phone, supplier.address, supplier.email) if x) or t('pas de coordonnées')
        self.d_head.setText(f"<b style='font-size:17px'>{supplier.name}</b><br><span style='color:#64748b'>{extra}</span>")
        linked = [p for p in ProductController.list(only_active=True) if getattr(p, 'supplier_id', None) == sid]
        self.d_info.setText(f"<table cellspacing='10'><tr><td><span style='color:#64748b'>{t('Reste à payer')}</span><br><b style='color:{'#b91c1c' if owed > 0 else '#0f172a'}'>{format_money(owed, cur)}</b></td>"
                            f"<td><span style='color:#64748b'>{t('Produits liés')}</span><br><b>{len(linked)}</b></td>"
                            f"<td><span style='color:#64748b'>{t('À commander')}</span><br><b>{len(order_message.products_to_order(sid))}</b></td></tr></table>")
        rests = {}
        for d in SupplierDebtService.list_debts(supplier_id=sid, only_active=True, limit=2000):
            if d.purchase_id:
                rests[d.purchase_id] = rests.get(d.purchase_id, 0.0) + float(d.amount_remaining or 0)
        lines = []
        for p in [p for p in PurchaseService.list(limit=2000) if p.supplier_id == sid and p.status != 'cancelled'][:4]:
            rest = rests.get(p.id, 0.0)
            tail = f"<b style='color:#b91c1c'>{t('reste')} {format_money(rest, cur)}</b>" if rest > 0 else f"<b style='color:#15803d'>{t('soldé')}</b>"
            lines.append(f"{p.date:%d/%m} · {p.invoice_number or '—'} · {format_money(p.total, cur)} — {tail}")
        self.d_buys.setText(("<span style='color:#64748b'>" + t('Derniers achats') + '</span><br>' + '<br>'.join(lines)) if lines else '')

    def _whatsapp(self) -> None:
        sid = self._selected_id()
        supplier = next((s for s in SupplierController.list() if s.id == sid), None) if sid else None
        if not supplier:
            warn(self, t('Sélectionnez un fournisseur.'))
            return
        from app.ui.dialogs.supplier_message_dialog import SupplierMessageDialog
        SupplierMessageDialog(supplier.id, supplier.name, supplier.phone or '', parent=self).exec()

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def select_supplier(self, supplier_id: int) -> None:
        if supplier_id not in self._ids:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.refresh()
        if supplier_id in self._ids:
            row = self._ids.index(supplier_id)
            self.table.selectRow(row)
            item = self.table.item(row, 0)
            if item:
                self.table.scrollToItem(item)

    def _add(self) -> None:
        dialog = ContactDialog('Nouveau fournisseur', parent=self)
        if dialog.exec() and dialog.data:
            SupplierController.create(dialog.data)
            self.refresh()

    def _edit(self) -> None:
        supplier_id = self._selected_id()
        if not supplier_id:
            warn(self, t('Sélectionnez un fournisseur.'))
            return
        supplier = SupplierController.get(supplier_id)
        dialog = ContactDialog('Modifier le fournisseur', supplier, parent=self)
        if dialog.exec() and dialog.data:
            SupplierController.update(supplier_id, dialog.data)
            self.refresh()

    def _settle_debt(self) -> None:
        if not self.state.can(perms.MANAGE_PURCHASES):
            warn(self, t("Vous n'avez pas l'autorisation de régler les dettes fournisseur."))
            return
        supplier_id = self._selected_id()
        if not supplier_id:
            warn(self, t('Sélectionnez un fournisseur.'))
            return
        supplier = SupplierController.get(supplier_id)
        if not supplier:
            return
        balance = SupplierDebtService.total_remaining(supplier_id)
        if balance <= 0:
            warn(self, t("Ce fournisseur n'a aucune dette active."))
            return
        dialog = DebtPaymentDialog(supplier.name, balance, parent=self)
        if not dialog.exec() or not dialog.result_data:
            return
        try:
            SupplierDebtService.pay_supplier(supplier_id, dialog.result_data['amount'], payment_method=dialog.result_data['payment_method'], note=dialog.result_data['note'], user_id=self.state.user_id, username=getattr(self.state.current_user, 'username', ''))
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        self.state.notify_data_changed()
        info(self, t('Remboursement fournisseur enregistré.'))

    def _delete_many(self, rows: list[int]) -> None:
        if not self.state.can(perms.MANAGE_SUPPLIERS):
            warn(self, t("Vous n'avez pas l'autorisation de supprimer un fournisseur."))
            return
        from app.services import audit_service
        user = getattr(self.state.current_user, 'username', '')

        def one(sid: int) -> None:
            SupplierController.delete(sid)
            audit_service.log_action('Suppression fournisseur', 'Supplier', str(sid), self.state.user_id, user)

        items = [(self._ids[r], self.table.item(r, 0).text()) for r in rows]
        if run_batch(self, t("Supprimer {n} fournisseurs ?"), items, one, t("fournisseur(s) supprimé(s)")):
            self.refresh()

    def _delete(self) -> None:
        rows = selected_rows(self.table)
        if len(rows) > 1:
            return self._delete_many(rows)
        supplier_id = self._selected_id()
        if not supplier_id:
            warn(self, t('Sélectionnez un fournisseur.'))
            return
        if not self.state.can(perms.MANAGE_SUPPLIERS):
            warn(self, t("Vous n'avez pas l'autorisation de supprimer un fournisseur."))
            return
        if confirm(self, t('Supprimer ce fournisseur ?')):
            SupplierController.delete(supplier_id)
            from app.services import audit_service
            audit_service.log_action('Suppression fournisseur', 'Supplier', str(supplier_id), self.state.user_id, getattr(self.state.current_user, 'username', ''))
            self.refresh()
