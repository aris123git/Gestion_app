"""Page de gestion des clients (CRUD, dettes, historique)."""
from __future__ import annotations
from app.i18n import t
from app.ui.widgets.batch import enable_multi, run_batch, selected_rows
from PySide6.QtCore import Qt, QTimer
from datetime import date

from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app.controllers.client_controller import ClientController
from app.services import permissions as perms, settings_service
from app.services.debt_service import DebtService
from app.services.loyalty_service import LoyaltyService
from app.ui.dialogs.contact_dialog import ContactDialog
from app.ui.dialogs.debt_history_dialog import DebtHistoryDialog
from app.ui.dialogs.debt_payment_dialog import DebtPaymentDialog
from app.ui.responsive import CLIENT_COLUMNS, LayoutProfile, TableColumnController
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.utils.helpers import format_money, format_quantity

class ClientsPage(QWidget):
    HEADERS = ['Nom', 'Téléphone', 'Dette']

    FILTERS = [('all', 'Tous'), ('with_debt', 'Avec dette'), ('overdue', 'Dette échue')]

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._ids: list[int] = []
        self._filter = 'all'
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(page_title(t('Clients')))
        header.addStretch()
        bulk = QPushButton(t('📣 Message groupé'))
        bulk.setToolTip(t('WhatsApp (un par un) ou e-mail à un groupe de clients'))
        bulk.clicked.connect(self._bulk_message)
        header.addWidget(bulk)
        add = QPushButton(t('+ Nouveau client'))
        add.setObjectName('Primary')
        add.clicked.connect(self._add)
        header.addWidget(add)
        layout.addLayout(header)
        kp = QHBoxLayout()
        self.k_count, self.k_due, self.k_late = QLabel(), QLabel(), QLabel()
        for k in (self.k_count, self.k_due, self.k_late):
            k.setTextFormat(Qt.TextFormat.RichText)
            kp.addWidget(make_card(k), 1)
        layout.addLayout(kp)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('Rechercher (nom, téléphone, note de dette)…'))
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _text='': self._search_timer.start())
        bar.addWidget(self.search, 1)
        self._chips = {}
        for key, label in self.FILTERS:
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
        self.d_head = QLabel(t('Sélectionnez un client.'))
        self.d_head.setTextFormat(Qt.TextFormat.RichText)
        self.d_head.setWordWrap(True)
        side.addWidget(self.d_head)
        self.d_info = QLabel()
        self.d_info.setTextFormat(Qt.TextFormat.RichText)
        self.d_info.setWordWrap(True)
        side.addWidget(self.d_info)
        self.d_ops = QLabel()
        self.d_ops.setTextFormat(Qt.TextFormat.RichText)
        self.d_ops.setWordWrap(True)
        side.addWidget(self.d_ops)
        side.addStretch(1)
        self.buttons = {}
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        specs = [(row1, 'settle', 'Encaisser', self._settle, 'Success'), (row1, 'whatsapp', 'WhatsApp', self._whatsapp, 'Primary'),
                 (row2, 'edit', 'Modifier', self._edit, ''), (row2, 'purchases', 'Historique achats', self._purchases, '')]
        for lay, key, label, handler, obj in specs:
            button = QPushButton(t(label))
            if obj:
                button.setObjectName(obj)
            button.clicked.connect(handler)
            self.buttons[key] = button
            lay.addWidget(button)
        more = QPushButton(t('Plus ▾'))
        menu = QMenu(more)
        self.add_debt_action = menu.addAction(t('+ Dette'), self._add_debt)
        menu.addAction(t('Échanger points'), self._redeem_points)
        menu.addAction(t('Historique des dettes'), self._history)
        menu.addSeparator()
        menu.addAction(t('Supprimer'), self._delete)
        more.setMenu(menu)
        self.buttons['more'] = more
        row2.addWidget(more)
        side.addLayout(row1)
        side.addLayout(row2)
        body.addLayout(side, 2)
        layout.addLayout(body, 1)
        self._chips['all'].setChecked(True)

    def _set_filter(self, key: str, refresh: bool = True) -> None:
        self._filter = key
        for k, chip in self._chips.items():
            chip.setChecked(k == key)
        if refresh:
            self.refresh()

    def refresh(self) -> None:
        self.add_debt_action.setVisible(self.state.can(perms.CREATE_MANUAL_CLIENT_DEBT))
        clients = ClientController.list(self.search.text().strip())
        mode = self._filter
        currency = settings_service.get_currency()
        everyone = ClientController.list('')
        all_summaries = DebtService.summaries_for_clients([c.id for c in everyone])
        total_due = sum(s['total_remaining'] for s in all_summaries.values())
        late = [s for s in all_summaries.values() if s['overdue_count'] > 0]
        self.k_count.setText(f"<span style='color:#64748b'>{t('Clients')}</span><br><b style='font-size:18px'>{len(everyone)}</b>")
        self.k_due.setText(f"<span style='color:#64748b'>{t('Dettes à recevoir')}</span><br><b style='font-size:18px'>{format_money(total_due, currency)}</b>")
        self.k_late.setText(f"<span style='color:#64748b'>{t('Dettes échues')}</span><br><b style='font-size:18px;color:#b91c1c'>{len(late)} {t('client(s)')}</b>")
        keep = self._selected_id()
        debt_summaries = DebtService.summaries_for_clients([client.id for client in clients])
        rows_data = []
        for client in clients:
            summary = debt_summaries.get(client.id, {'total_remaining': 0.0, 'active_count': 0, 'overdue_count': 0, 'debts': []})
            if mode == 'with_debt' and summary['total_remaining'] <= 0:
                continue
            if mode == 'overdue' and summary['overdue_count'] <= 0:
                continue
            rows_data.append((client, summary))
        search = self.search.text().strip()
        if search:
            seen = {c.id for c, _ in rows_data}
            extra_clients = []
            for debt in DebtService.list_debts(search=search, limit=300):
                if debt.client_id in seen:
                    continue
                client = ClientController.get(debt.client_id)
                if not client:
                    continue
                extra_clients.append(client)
                seen.add(client.id)
            extra_summaries = DebtService.summaries_for_clients([client.id for client in extra_clients])
            for client in extra_clients:
                summary = extra_summaries.get(client.id, {'total_remaining': 0.0, 'active_count': 0, 'overdue_count': 0, 'debts': []})
                if mode == 'with_debt' and summary['total_remaining'] <= 0:
                    continue
                if mode == 'overdue' and summary['overdue_count'] <= 0:
                    continue
                rows_data.append((client, summary))
        self._ids = [c.id for c, _ in rows_data]
        self._summaries = {c.id: s for c, s in rows_data}
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows_data))
        for row, (client, summary) in enumerate(rows_data):
            self.table.setItem(row, 0, QTableWidgetItem(client.name))
            self.table.setItem(row, 1, QTableWidgetItem(client.phone))
            owed = summary['total_remaining']
            debt_item = QTableWidgetItem(format_money(owed, currency) if owed > 0 else '—')
            debt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if summary['overdue_count'] > 0:
                debt_item.setForeground(Qt.GlobalColor.red)
            elif owed <= 0:
                debt_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 2, debt_item)
        self.table.blockSignals(False)
        if keep in self._ids:
            self.table.setCurrentCell(self._ids.index(keep), 0)
        self._show()

    def _show(self) -> None:
        cid = self._selected_id()
        for b in self.buttons.values():
            b.setEnabled(bool(cid))
        if not cid:
            self.d_head.setText(t('Sélectionnez un client.'))
            self.d_info.setText('')
            self.d_ops.setText('')
            return
        client = ClientController.get(cid)
        if not client:
            return
        cur = settings_service.get_currency()
        s = DebtService.client_summary(cid)
        points = LoyaltyService.get_balance(cid)
        self.d_head.setText(f"<b style='font-size:17px'>{client.name}</b><br><span style='color:#64748b'>{client.phone or t('pas de numéro')}{' · ' + client.address if client.address else ''}</span>")
        late = ''
        if s['overdue_count']:
            days = max((date.today() - d.due_date).days for d in s['debts'] if d.is_overdue)
            late = f"<br><span style='color:#b91c1c'>{t('échue depuis')} {days} {t('jour(s)')}</span>"
        owed_color = '#b91c1c' if s['overdue_count'] else '#0f172a'
        self.d_info.setText(f"<table cellspacing='10'><tr><td><span style='color:#64748b'>{t('Dette')}</span><br><b style='color:{owed_color}'>{format_money(s['total_remaining'], cur)}</b>{late}</td>"
                            f"<td><span style='color:#64748b'>{t('Points')}</span><br><b>{format_quantity(points)}</b></td>"
                            f"<td><span style='color:#64748b'>{t('Dernière visite')}</span><br><b>{client.last_visit or '—'}</b></td>"
                            f"<td><span style='color:#64748b'>{t('Achats')}</span><br><b>{client.purchase_count or 0}</b></td></tr></table>")
        lines = []
        for d in (s['debts'] or [])[:4]:
            when = d.created_at.strftime('%d/%m') if getattr(d, 'created_at', None) else ''
            lines.append(f"{when} · {t('Dette')} {format_money(d.amount_initial, cur)} · {t('reste')} {format_money(d.amount_remaining, cur)}" + (f" · {d.note}" if d.note else ''))
        self.d_ops.setText(("<span style='color:#64748b'>" + t('Dernières dettes') + "</span><br>" + '<br>'.join(lines)) if lines else '')
        self.buttons['settle'].setEnabled(s['total_remaining'] > 0)

    def _whatsapp(self) -> None:
        cid = self._selected_id()
        client = ClientController.get(cid) if cid else None
        if not client:
            warn(self, t('Sélectionnez un client.'))
            return
        from app.ui.dialogs.client_message_dialog import ClientMessageDialog
        debt = DebtService.client_summary(cid)['total_remaining']
        ClientMessageDialog(client.name, client.phone or '', debt, bool(getattr(client, 'no_marketing', False)), parent=self).exec()

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def select_client(self, client_id: int) -> None:
        if client_id not in self._ids:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self._set_filter('all', refresh=False)
            self.refresh()
        if client_id in self._ids:
            row = self._ids.index(client_id)
            self.table.selectRow(row)
            item = self.table.item(row, 0)
            if item:
                self.table.scrollToItem(item)

    def _add(self) -> None:
        can_open_debt = self.state.can(perms.CREATE_MANUAL_CLIENT_DEBT)
        dialog = ContactDialog('Nouveau client', with_debt=can_open_debt, parent=self, with_marketing=True, with_fiscal=True)
        if dialog.exec() and dialog.data:
            ClientController.create(dialog.data, user_id=self.state.user_id, username=getattr(self.state.current_user, 'username', ''))
            self.refresh()
            self.state.notify_data_changed()

    def _bulk_message(self) -> None:
        from app.ui.dialogs.bulk_message_dialog import BulkMessageDialog
        BulkMessageDialog(self, self.state.user_id, getattr(self.state.current_user, 'username', '')).exec()

    def _edit(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, t('Sélectionnez un client.'))
            return
        client = ClientController.get(client_id)
        can_see_debt = self.state.can(perms.MANAGE_CLIENT_DEBTS)
        dialog = ContactDialog('Modifier le client', client, with_debt=can_see_debt, parent=self, with_marketing=True, with_fiscal=True)
        if dialog.exec() and dialog.data:
            ClientController.update(client_id, dialog.data)
            self.refresh()
            self.state.notify_data_changed()

    def _add_debt(self) -> None:
        if not self.state.can(perms.CREATE_MANUAL_CLIENT_DEBT):
            warn(self, t('Seul un administrateur peut saisir une dette hors caisse.'))
            return
        client_id = self._selected_id()
        if not client_id:
            warn(self, t('Sélectionnez un client.'))
            return
        from app.ui.dialogs.manual_debt_dialog import ManualDebtDialog
        dialog = ManualDebtDialog(parent=self)
        dialog.client_search.set_client(client_id)
        if not dialog.exec() or not dialog.result_data:
            return
        data = dialog.result_data
        try:
            ClientController.add_debt(data['client_id'], data['amount'], note=data['note'], due_date=data.get('due_date'), user_id=self.state.user_id, username=getattr(self.state.current_user, 'username', ''))
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        self.state.notify_data_changed()
        info(self, t('Dette enregistrée.'))

    def _settle(self) -> None:
        if not self.state.can(perms.MANAGE_CLIENT_DEBTS) and (not self.state.can(perms.MANAGE_CLIENTS)):
            warn(self, t("Vous n'avez pas l'autorisation de régler une dette."))
            return
        client_id = self._selected_id()
        if not client_id:
            warn(self, t('Sélectionnez un client.'))
            return
        client = ClientController.get(client_id)
        if not client:
            return
        summary = DebtService.client_summary(client_id)
        if summary['total_remaining'] <= 0:
            warn(self, t("Ce client n'a aucune dette active."))
            return
        dialog = DebtPaymentDialog(client.name, summary['total_remaining'], parent=self)
        if not dialog.exec() or not dialog.result_data:
            return
        try:
            ClientController.settle_debt(client_id, dialog.result_data['amount'], payment_method=dialog.result_data['payment_method'], note=dialog.result_data['note'], user_id=self.state.user_id, username=getattr(self.state.current_user, 'username', ''))
        except ValueError as exc:
            warn(self, str(exc))
            return
        after = DebtService.client_summary(client_id)
        from app.ui.dialogs.debt_payment_receipt_dialog import DebtPaymentReceiptDialog
        DebtPaymentReceiptDialog(client_name=client.name, amount=dialog.result_data['amount'], payment_method=dialog.result_data['payment_method'], remaining_after=after['total_remaining'], note=dialog.result_data['note'], cashier=getattr(self.state.current_user, 'username', '') or '', parent=self).exec()
        self.refresh()
        self.state.notify_data_changed()

    def _redeem_points(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, t('Sélectionnez un client.'))
            return
        client = ClientController.get(client_id)
        if not client:
            return
        balance = LoyaltyService.get_balance(client_id)
        if balance <= 0:
            warn(self, t("Ce client n'a aucun point de fidélité."))
            return
        if getattr(self.state.current_user, 'role', '') == perms.ROLE_CASHIER:
            from app.ui.dialogs.authorize_dialog import require_admin_authorization
            ok, admin_name = require_admin_authorization(self, "L'échange de points nécessite l'autorisation d'un administrateur.")
            if not ok:
                return
        else:
            admin_name = ''
        from PySide6.QtWidgets import QInputDialog
        points, ok = QInputDialog.getDouble(self, 'Échanger des points', f'Points disponibles : {balance:g}\nNombre à échanger :', min(balance, 100.0), 0.01, balance, 2)
        if not ok or points <= 0:
            return
        try:
            remaining = LoyaltyService.redeem(client_id, points, user_id=self.state.user_id, username=getattr(self.state.current_user, 'username', ''))
        except ValueError as exc:
            warn(self, str(exc))
            return
        from app.services import audit_service
        audit_service.log_action('Échange points', 'Loyalty', f'client={client_id} points={points}' + (f' autorisé_par={admin_name}' if admin_name else ''), self.state.user_id, getattr(self.state.current_user, 'username', ''))
        self.refresh()
        info(self, f'Échange enregistré. Solde restant : {remaining:g} pts.')

    def _purchases(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, t('Sélectionnez un client.'))
            return
        client = ClientController.get(client_id)
        if not client:
            return
        from app.ui.dialogs.client_purchases_dialog import ClientPurchasesDialog
        ClientPurchasesDialog(client_id, client.name, state=self.state, parent=self).exec()

    def _history(self) -> None:
        client_id = self._selected_id()
        if not client_id:
            warn(self, t('Sélectionnez un client.'))
            return
        client = ClientController.get(client_id)
        if not client:
            return
        DebtHistoryDialog(client_id, client.name, parent=self).exec()

    def _delete_many(self, rows: list[int]) -> None:
        if not self.state.can(perms.MANAGE_CLIENTS):
            warn(self, t("Vous n'avez pas l'autorisation de supprimer un client."))
            return
        from app.services import audit_service
        user = getattr(self.state.current_user, 'username', '')

        def one(cid: int) -> None:
            if DebtService.list_debts(client_id=cid, limit=1):
                raise ValueError(t('a un historique de dettes'))
            if ClientController.has_sales(cid):
                raise ValueError(t('a un historique de ventes'))
            ClientController.delete(cid)
            audit_service.log_action('Suppression client', 'Client', str(cid), self.state.user_id, user)

        items = [(self._ids[r], self.table.item(r, 0).text()) for r in rows]
        if run_batch(self, t("Supprimer {n} clients ?\n\nCeux qui ont des ventes ou des dettes seront conservés."), items, one, t("client(s) supprimé(s)")):
            self.refresh()
            self.state.notify_data_changed()

    def _delete(self) -> None:
        rows = selected_rows(self.table)
        if len(rows) > 1:
            return self._delete_many(rows)
        client_id = self._selected_id()
        if not client_id:
            warn(self, t('Sélectionnez un client.'))
            return
        if not self.state.can(perms.MANAGE_CLIENTS):
            warn(self, t("Vous n'avez pas l'autorisation de supprimer un client."))
            return
        if DebtService.list_debts(client_id=client_id, limit=1):
            warn(self, t('Impossible de supprimer un client ayant un historique de dettes. Réglez ou conservez la fiche pour la traçabilité.'))
            return
        if ClientController.has_sales(client_id):
            warn(self, t('Impossible de supprimer un client ayant un historique de ventes. Conservez la fiche pour la traçabilité.'))
            return
        if confirm(self, t('Supprimer ce client ?')):
            try:
                ClientController.delete(client_id)
            except ValueError as exc:
                warn(self, str(exc))
                return
            from app.services import audit_service
            audit_service.log_action('Suppression client', 'Client', str(client_id), self.state.user_id, getattr(self.state.current_user, 'username', ''))
            self.refresh()
            self.state.notify_data_changed()
