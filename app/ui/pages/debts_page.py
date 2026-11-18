"""Dettes clients : une ligne par client (total dû), détail = ses différentes dettes, règlements, relance WhatsApp."""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.controllers.client_controller import ClientController
from app.i18n import t
from app.models.debt import STATUS_CANCELLED, STATUS_OPEN, STATUS_PAID, STATUS_PARTIAL
from app.services import permissions as perms, settings_service
from app.services.debt_service import DebtService
from app.ui.dialogs.debt_history_dialog import DebtHistoryDialog
from app.ui.dialogs.debt_payment_dialog import DebtPaymentDialog
from app.ui.dialogs.manual_debt_dialog import ManualDebtDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import info, make_card, page_title, warn
from app.utils.helpers import format_datetime, format_money

STATUS_LABELS = {STATUS_OPEN: 'En cours', STATUS_PARTIAL: 'Partielle', STATUS_PAID: 'Soldée', STATUS_CANCELLED: 'Annulée'}
FILTERS = (('unpaid', 'Non payées'), ('overdue', 'Échues'), ('paid', 'Payées'), ('all', 'Tout'))
SORTS = (('late', 'Plus en retard'), ('amount', 'Montant restant'), ('client', 'Client A → Z'), ('recent', 'Plus récentes'))


def _cell(text: str, right: bool = False, color: Optional[str] = None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    if right:
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    return it


def _table(headers: list[str]) -> QTableWidget:
    tb = QTableWidget(0, len(headers))
    tb.setHorizontalHeaderLabels([t(h) for h in headers])
    tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tb.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tb.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    tb.verticalHeader().setVisible(False)
    tb.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    return tb


class DebtsPage(QWidget):
    def __init__(self, state: AppState, embedded: bool = False, on_open_client: Optional[Callable[[int], None]] = None):
        super().__init__()
        self.state = state
        self.on_open_client = on_open_client
        self._mode = 'unpaid'
        self._groups: list[dict] = []
        self._debts: list = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0) if embedded else root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)
        top = QHBoxLayout()
        if not embedded:
            top.addWidget(page_title(t('Dettes clients')))
        top.addStretch()
        self.remind_button = QPushButton(t('📣 Relancer les clients endettés'))
        self.remind_button.setToolTip(t('Message groupé WhatsApp / e-mail aux clients qui ont une dette'))
        self.remind_button.clicked.connect(self._remind_all)
        top.addWidget(self.remind_button)
        self.add_debt_btn = QPushButton(t('+ Nouvelle dette'))
        self.add_debt_btn.setObjectName('Primary')
        self.add_debt_btn.setToolTip(t("Saisie libre hors caisse — réservée à l'administrateur"))
        self.add_debt_btn.clicked.connect(self._add_manual_debt)
        top.addWidget(self.add_debt_btn)
        root.addLayout(top)
        kp = QHBoxLayout()
        self.k_due, self.k_late, self.k_in = QLabel(), QLabel(), QLabel()
        for k in (self.k_due, self.k_late, self.k_in):
            k.setTextFormat(Qt.TextFormat.RichText)
            k.setMinimumHeight(44)
            kp.addWidget(make_card(k), 1)
        root.addLayout(kp)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('Rechercher (client, téléphone, note)…'))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _=None: self._timer.start())
        bar.addWidget(self.search, 1)
        self._chips = {}
        for key, label in FILTERS:
            chip = QPushButton(t(label))
            chip.setCheckable(True)
            chip.setStyleSheet('QPushButton:checked { background: #2563eb; color: #ffffff; border-color: #2563eb; }')
            chip.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self._chips[key] = chip
            bar.addWidget(chip)
        bar.addWidget(QLabel(t('Trier :')))
        self.sort_combo = QComboBox()
        for label, value in [(l, v) for v, l in SORTS]:
            self.sort_combo.addItem(t(label), value)
        self.sort_combo.currentIndexChanged.connect(lambda _=0: self.refresh())
        bar.addWidget(self.sort_combo)
        root.addLayout(bar)
        body = QHBoxLayout()
        self.clients = _table(['Client', 'Reste dû', 'Dettes', 'Échéance'])
        self.clients.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.clients.currentCellChanged.connect(lambda *_: self._show_client())
        body.addWidget(self.clients, 2)
        side = QVBoxLayout()
        self.d_head = QLabel(t('Sélectionnez un client.'))
        self.d_head.setTextFormat(Qt.TextFormat.RichText)
        self.d_head.setWordWrap(True)
        side.addWidget(self.d_head)
        self.debts = _table(['Date', 'Vente', 'Initial', 'Reste', 'Échéance', 'Statut'])
        self.debts.horizontalHeader().setStretchLastSection(True)
        self.debts.currentCellChanged.connect(lambda *_: self._show_debt())
        side.addWidget(self.debts, 2)
        self.d_pay = QLabel()
        self.d_pay.setTextFormat(Qt.TextFormat.RichText)
        self.d_pay.setWordWrap(True)
        side.addWidget(self.d_pay, 1)
        row = QHBoxLayout()
        self.settle_btn = QPushButton(t('Encaisser'))
        self.settle_btn.setObjectName('Success')
        self.settle_btn.clicked.connect(self._settle)
        self.wa_btn = QPushButton(t('WhatsApp'))
        self.wa_btn.setObjectName('Primary')
        self.wa_btn.clicked.connect(self._whatsapp)
        self.card_btn = QPushButton(t('Fiche client'))
        self.card_btn.clicked.connect(self._open_card)
        self.history_btn = QPushButton(t('Historique'))
        self.history_btn.clicked.connect(self._open_history)
        for b in (self.settle_btn, self.wa_btn, self.card_btn, self.history_btn):
            row.addWidget(b)
        side.addLayout(row)
        body.addLayout(side, 3)
        root.addLayout(body, 1)
        self._chips['unpaid'].setChecked(True)

    # ---- filtres --------------------------------------------------------------------------
    def _set_filter(self, key: str) -> None:
        self._mode = key
        for k, c in self._chips.items():
            c.setChecked(k == key)
        self.refresh()

    def show_unpaid(self) -> None:
        self._set_filter('unpaid')

    # ---- données --------------------------------------------------------------------------
    @staticmethod
    def _late_days(debt) -> int:
        if debt.is_overdue and debt.due_date:
            return (date.today() - debt.due_date).days
        return 0

    def refresh(self) -> None:
        self.add_debt_btn.setVisible(self.state.can(perms.CREATE_MANUAL_CLIENT_DEBT))
        if not self.state.can(perms.MANAGE_CLIENT_DEBTS) and not self.state.can(perms.MANAGE_CLIENTS):
            self.clients.setRowCount(0)
            self.d_head.setText(t('Accès restreint aux dettes clients.'))
            return
        cur = settings_service.get_currency()
        everyone = DebtService.list_debts(filter_mode='unpaid', limit=20000)
        due = sum(float(d.amount_remaining) for d in everyone)
        late = [d for d in everyone if d.is_overdue]
        month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        paid_month = sum(float(p.amount) for p in DebtService.list_payments(limit=20000) if p.payment_date >= month)
        self.k_due.setText(f"<span style='color:#64748b'>{t('À recevoir')}</span><br><b style='font-size:18px'>{format_money(due, cur)}</b> <span style='color:#64748b'>({len(everyone)})</span>")
        self.k_late.setText(f"<span style='color:#64748b'>{t('Échues')}</span><br><b style='font-size:18px;color:#b91c1c'>{format_money(sum(float(d.amount_remaining) for d in late), cur)}</b> <span style='color:#64748b'>({len(late)})</span>")
        self.k_in.setText(f"<span style='color:#64748b'>{t('Encaissé ce mois')}</span><br><b style='font-size:18px;color:#15803d'>{format_money(paid_month, cur)}</b>")
        debts = DebtService.list_debts(search=self.search.text().strip(), filter_mode=self._mode, limit=20000)
        groups: dict[int, dict] = {}
        for d in debts:
            g = groups.setdefault(d.client_id, {'id': d.client_id, 'name': d.client.name if d.client else '—', 'phone': (d.client.phone if d.client else '') or '',
                                                'debts': [], 'remaining': 0.0, 'late': 0, 'next_due': None, 'recent': d.created_at})
            g['debts'].append(d)
            if d.is_active:
                g['remaining'] += float(d.amount_remaining or 0)
                g['late'] = max(g['late'], self._late_days(d))
                if d.due_date and (g['next_due'] is None or d.due_date < g['next_due']):
                    g['next_due'] = d.due_date
            g['recent'] = max(g['recent'], d.created_at)
        sort = self.sort_combo.currentData()
        items = list(groups.values())
        if sort == 'amount':
            items.sort(key=lambda g: -g['remaining'])
        elif sort == 'client':
            items.sort(key=lambda g: g['name'].lower())
        elif sort == 'recent':
            items.sort(key=lambda g: g['recent'], reverse=True)
        else:
            items.sort(key=lambda g: (-g['late'], -g['remaining']))
        keep = self._current_client_id()
        self._groups = items
        self.clients.blockSignals(True)
        self.clients.setRowCount(len(items))
        for r, g in enumerate(items):
            if g['late']:
                due_cell = _cell(f"{g['next_due']:%d/%m} · {g['late']} {t('j de retard')}", color='#b91c1c')
            elif g['next_due']:
                due_cell = _cell(f"{g['next_due']:%d/%m/%Y}")
            else:
                due_cell = _cell('—', color='#64748b')
            rem = _cell(format_money(g['remaining'], cur) if g['remaining'] > 0 else '—', True, '#b91c1c' if g['late'] else None)
            for c, it in enumerate([_cell(g['name']), rem, _cell(str(len(g['debts'])), True), due_cell]):
                self.clients.setItem(r, c, it)
        self.clients.blockSignals(False)
        ids = [g['id'] for g in items]
        if keep in ids:
            self.clients.setCurrentCell(ids.index(keep), 0)
        self._show_client()

    # ---- détail ---------------------------------------------------------------------------
    def _current_client_id(self) -> Optional[int]:
        r = self.clients.currentRow()
        return self._groups[r]['id'] if 0 <= r < len(self._groups) else None

    def _group(self) -> Optional[dict]:
        r = self.clients.currentRow()
        return self._groups[r] if 0 <= r < len(self._groups) else None

    def _selected_debt(self):
        g, r = self._group(), self.debts.currentRow()
        return g['debts'][r] if g and 0 <= r < len(g['debts']) else None

    def _show_client(self) -> None:
        g = self._group()
        for b in (self.settle_btn, self.wa_btn, self.card_btn, self.history_btn):
            b.setEnabled(bool(g))
        self.debts.blockSignals(True)
        if not g:
            self.d_head.setText(t('Sélectionnez un client.'))
            self.debts.setRowCount(0)
            self.d_pay.setText('')
            self.debts.blockSignals(False)
            return
        cur = settings_service.get_currency()
        late = f" · <span style='color:#b91c1c'>{t('échue depuis')} {g['late']} {t('jour(s)')}</span>" if g['late'] else ''
        self.d_head.setText(f"<b style='font-size:17px'>{g['name']}</b> — {t('reste dû')} <b>{format_money(g['remaining'], cur)}</b><br>"
                            f"<span style='color:#64748b'>{g['phone'] or t('pas de numéro')}</span>{late}")
        rows = sorted(g['debts'], key=lambda d: d.created_at)
        g['debts'] = rows
        self.debts.setRowCount(len(rows))
        for r, d in enumerate(rows):
            ticket = '—'
            if d.sale is not None:
                ticket = getattr(d.sale, 'ticket_number', '') or str(d.sale_id)
            status = t(STATUS_LABELS.get(d.status, d.status))
            overdue = bool(d.is_overdue)
            vals = [_cell(d.created_at.strftime('%d/%m/%Y') if d.created_at else '—'), _cell(ticket), _cell(format_money(d.amount_initial, cur), True),
                    _cell(format_money(d.amount_remaining, cur), True), _cell(d.due_date.strftime('%d/%m/%Y') if d.due_date else '—', color='#b91c1c' if overdue else None),
                    _cell(status, color='#b91c1c' if overdue else None)]
            for c, it in enumerate(vals):
                self.debts.setItem(r, c, it)
        self.debts.blockSignals(False)
        self._show_debt()

    def _show_debt(self) -> None:
        d = self._selected_debt()
        g = self._group()
        if not d:
            self.d_pay.setText(("<span style='color:#64748b'>" + t("Choisissez une dette pour voir ses règlements. Sans choix, « Encaisser » règle les plus anciennes dettes d'abord.") + "</span>") if g else '')
            return
        cur = settings_service.get_currency()
        pays = DebtService.list_payments(debt_id=d.id, limit=50)
        note = f"{t('Note')} : {d.note}<br>" if d.note else ''
        if pays:
            lines = '<br>'.join(f"{format_datetime(p.payment_date)} · {format_money(p.amount, cur)} · {p.payment_method}" for p in pays[:6])
        else:
            lines = "<span style='color:#64748b'>" + t("Aucun règlement pour l'instant") + '</span>'
        self.d_pay.setText(f"{note}<span style='color:#64748b'>{t('Règlements')}</span><br>{lines}")

    # ---- actions --------------------------------------------------------------------------
    def _user(self):
        return self.state.user_id, getattr(self.state.current_user, 'username', '')

    def _add_manual_debt(self) -> None:
        if not self.state.can(perms.CREATE_MANUAL_CLIENT_DEBT):
            warn(self, t('Seul un administrateur peut saisir une dette hors caisse.'))
            return
        dialog = ManualDebtDialog(parent=self)
        if not dialog.exec() or not dialog.result_data:
            return
        data = dialog.result_data
        try:
            ClientController.add_debt(data['client_id'], data['amount'], note=data['note'], due_date=data.get('due_date'), user_id=self.state.user_id, username=self._user()[1])
        except ValueError as exc:
            warn(self, str(exc))
            return
        info(self, t('Dette enregistrée.'))
        self._set_filter('unpaid')
        self.state.notify_data_changed()

    def _settle(self) -> None:
        if not self.state.can(perms.MANAGE_CLIENT_DEBTS) and not self.state.can(perms.MANAGE_CLIENTS):
            warn(self, t("Vous n'avez pas l'autorisation de régler une dette."))
            return
        g = self._group()
        if not g:
            warn(self, t('Sélectionnez un client.'))
            return
        debt = self._selected_debt()
        if debt is not None and (not debt.is_active or float(debt.amount_remaining or 0) <= 0):
            warn(self, t("Cette dette n'a plus de reste dû."))
            return
        rest = float(debt.amount_remaining) if debt is not None else g['remaining']
        if rest <= 0:
            warn(self, t("Ce client n'a aucune dette active."))
            return
        dialog = DebtPaymentDialog(g['name'], rest, parent=self)
        if not dialog.exec() or not dialog.result_data:
            return
        res = dialog.result_data
        uid, uname = self._user()
        try:
            if debt is not None:
                payment = DebtService.pay_debt(debt.id, res['amount'], payment_method=res['payment_method'], note=res['note'], user_id=uid, username=uname)
                pid = getattr(payment, 'id', None)
            else:
                ClientController.settle_debt(g['id'], res['amount'], payment_method=res['payment_method'], note=res['note'], user_id=uid, username=uname)
                pid = None
        except ValueError as exc:
            warn(self, str(exc))
            return
        after = DebtService.client_summary(g['id'])['total_remaining'] if debt is None else max(rest - res['amount'], 0.0)
        from app.ui.dialogs.debt_payment_receipt_dialog import DebtPaymentReceiptDialog
        DebtPaymentReceiptDialog(client_name=g['name'], amount=res['amount'], payment_method=res['payment_method'], remaining_after=after, note=res['note'], cashier=uname or '', payment_id=pid, parent=self).exec()
        self.refresh()
        self.state.notify_data_changed()

    def _whatsapp(self) -> None:
        g = self._group()
        if not g:
            warn(self, t('Sélectionnez un client.'))
            return
        client = ClientController.get(g['id'])
        from app.ui.dialogs.client_message_dialog import ClientMessageDialog
        ClientMessageDialog(g['name'], g['phone'], g['remaining'], bool(getattr(client, 'no_marketing', False)), parent=self).exec()

    def _remind_all(self) -> None:
        from app.services import messaging_service as ms
        from app.ui.dialogs.bulk_message_dialog import BulkMessageDialog
        dlg = BulkMessageDialog(self, *self._user())
        dlg.segment.setCurrentIndex(max(dlg.segment.findData(ms.SEG_DEBT), 0))
        dlg.exec()

    def _open_card(self) -> None:
        cid = self._current_client_id()
        if cid and self.on_open_client:
            self.on_open_client(cid)

    def _open_history(self) -> None:
        g = self._group()
        if g:
            DebtHistoryDialog(g['id'], g['name'], parent=self).exec()
            self.refresh()
