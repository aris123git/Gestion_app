"""Avoirs clients (crédit magasin) : liste + détail, création avec un vrai client, utilisation partielle."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.controllers.client_controller import ClientController
from app.i18n import t
from app.models.avoir import STATUS_ACTIVE, STATUS_CANCELLED, STATUS_EXPIRED, STATUS_PARTIAL, STATUS_USED
from app.services import settings_service
from app.services.avoir_service import AvoirService
from app.ui.widgets.batch import enable_multi, run_batch, selected_rows
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.ui.widgets.money_spin import MoneySpinBox
from app.utils.helpers import format_money

STATUS_LABELS = {STATUS_ACTIVE: 'Actif', STATUS_PARTIAL: 'Partiel', STATUS_USED: 'Soldé', STATUS_EXPIRED: 'Expiré', STATUS_CANCELLED: 'Annulé'}
FILTERS = (('active', 'Actifs'), ('used', 'Soldés'), ('cancelled', 'Annulés'), ('all', 'Tous'))
_FILTER_STATUSES = {'active': (STATUS_ACTIVE, STATUS_PARTIAL), 'used': (STATUS_USED,), 'cancelled': (STATUS_CANCELLED, STATUS_EXPIRED)}


def _cell(text: str, right: bool = False, color: Optional[str] = None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    if right:
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    return it


class NewAvoirDialog(QDialog):
    """Nouvel avoir : client (liste ou vide), montant, motif, expiration facultative."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t('Nouvel avoir'))
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.client = QComboBox()
        self.client.setEditable(True)
        self.client.addItem(t('— Sans client —'), None)
        for c in ClientController.list(''):
            self.client.addItem(c.name, c.id)
        self.client.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.amount = MoneySpinBox()
        self.amount.setRange(1, 50000000)
        self.amount.setDecimals(3)
        self.amount.setValue(1000)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t('Motif (retour, rendu monnaie, geste commercial…)'))
        self.has_expiry = QCheckBox(t("Date d'expiration"))
        self.expiry = QDateEdit(QDate.currentDate().addMonths(3))
        self.expiry.setCalendarPopup(True)
        self.expiry.setEnabled(False)
        self.has_expiry.toggled.connect(self.expiry.setEnabled)
        form.addRow(t('Client'), self.client)
        form.addRow(t('Montant'), self.amount)
        form.addRow(t('Motif'), self.reason)
        form.addRow(self.has_expiry, self.expiry)
        row = QHBoxLayout()
        no = QPushButton(t('Annuler'))
        no.clicked.connect(self.reject)
        ok = QPushButton(t("Créer l'avoir"))
        ok.setObjectName('Success')
        ok.clicked.connect(self.accept)
        row.addWidget(no)
        row.addWidget(ok)
        form.addRow(row)

    def values(self) -> dict:
        cid = self.client.currentData() if self.client.currentText() == self.client.itemText(self.client.currentIndex()) else None
        name = self.client.currentText().strip() if cid else (self.client.currentText().strip() if self.client.currentText() != t('— Sans client —') else '')
        d = self.expiry.date()
        return dict(amount=float(self.amount.value()), client_id=cid, customer_name=name, reason=self.reason.text().strip(),
                    expires_on=date(d.year(), d.month(), d.day()) if self.has_expiry.isChecked() else None)


class UseAvoirDialog(QDialog):
    def __init__(self, rest: float, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t('Utiliser l\'avoir'))
        form = QFormLayout(self)
        self.amount = MoneySpinBox()
        self.amount.setRange(1, rest)
        self.amount.setDecimals(3)
        self.amount.setValue(rest)
        self.note = QLineEdit()
        self.note.setPlaceholderText(t('Note (facultatif)'))
        form.addRow(t('Montant utilisé'), self.amount)
        form.addRow(t('Note'), self.note)
        row = QHBoxLayout()
        no = QPushButton(t('Annuler'))
        no.clicked.connect(self.reject)
        ok = QPushButton(t('Enregistrer'))
        ok.setObjectName('Success')
        ok.clicked.connect(self.accept)
        row.addWidget(no)
        row.addWidget(ok)
        form.addRow(row)


class AvoirsPage(QWidget):
    def __init__(self, state, parent=None, embedded: bool = False, on_open_client: Optional[Callable[[int], None]] = None):
        super().__init__(parent)
        self.state = state
        self.on_open_client = on_open_client
        self._filter = 'active'
        self._rows: list = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0) if embedded else root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)
        top = QHBoxLayout()
        if not embedded:
            top.addWidget(page_title(t('Avoirs clients')))
        top.addStretch()
        self.new_button = QPushButton(t('+ Nouvel avoir'))
        self.new_button.setObjectName('Primary')
        self.new_button.clicked.connect(self._create)
        top.addWidget(self.new_button)
        root.addLayout(top)
        kp = QHBoxLayout()
        self.k_due, self.k_used, self.k_soon = QLabel(), QLabel(), QLabel()
        for k in (self.k_due, self.k_used, self.k_soon):
            k.setTextFormat(Qt.TextFormat.RichText)
            k.setMinimumHeight(44)
            kp.addWidget(make_card(k), 1)
        root.addLayout(kp)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('Rechercher (client, n°, motif)…'))
        self.search.textChanged.connect(lambda _=None: self.refresh())
        bar.addWidget(self.search, 1)
        self._chips = {}
        for key, label in FILTERS:
            chip = QPushButton(t(label))
            chip.setCheckable(True)
            chip.setStyleSheet('QPushButton:checked { background: #2563eb; color: #ffffff; border-color: #2563eb; }')
            chip.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self._chips[key] = chip
            bar.addWidget(chip)
        root.addLayout(bar)
        body = QHBoxLayout()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([t('N°'), t('Client'), t('Reste'), t('Statut')])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        enable_multi(self.table)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.currentCellChanged.connect(lambda *_: self._show())
        body.addWidget(self.table, 3)
        side = QVBoxLayout()
        self.d_head = QLabel(t('Sélectionnez un avoir.'))
        self.d_head.setTextFormat(Qt.TextFormat.RichText)
        self.d_head.setWordWrap(True)
        side.addWidget(self.d_head)
        self.d_info = QLabel()
        self.d_info.setTextFormat(Qt.TextFormat.RichText)
        side.addWidget(self.d_info)
        self.d_uses = QLabel()
        self.d_uses.setTextFormat(Qt.TextFormat.RichText)
        self.d_uses.setWordWrap(True)
        side.addWidget(self.d_uses)
        side.addStretch(1)
        row = QHBoxLayout()
        self.use_button = QPushButton(t('Utiliser…'))
        self.use_button.setObjectName('Success')
        self.use_button.clicked.connect(self._redeem_selected)
        self.card_button = QPushButton(t('Fiche client'))
        self.card_button.clicked.connect(self._open_card)
        self.cancel_button = QPushButton(t('Annuler'))
        self.cancel_button.setObjectName('DangerOutline')
        self.cancel_button.clicked.connect(self._cancel_selected)
        for b in (self.use_button, self.card_button, self.cancel_button):
            row.addWidget(b)
        side.addLayout(row)
        body.addLayout(side, 2)
        root.addLayout(body, 1)
        self._chips['active'].setChecked(True)

    # ---- données --------------------------------------------------------------------------
    def _set_filter(self, key: str) -> None:
        self._filter = key
        for k, c in self._chips.items():
            c.setChecked(k == key)
        self.refresh()

    @staticmethod
    def _name(a) -> str:
        if a.customer_name:
            return a.customer_name
        if a.client_id:
            c = ClientController.get(a.client_id)
            return c.name if c else f'Client #{a.client_id}'
        return t('— sans client —')

    def refresh(self) -> None:
        cur = settings_service.get_currency()
        everything = AvoirService.list(limit=5000)
        active = [a for a in everything if a.status in (STATUS_ACTIVE, STATUS_PARTIAL)]
        month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        soon = [a for a in active if a.expires_on and a.expires_on <= date.today() + timedelta(days=14)]
        self.k_due.setText(f"<span style='color:#64748b'>{t('Avoirs à utiliser')}</span><br><b style='font-size:18px'>{format_money(sum(float(a.amount_remaining) for a in active), cur)}</b> <span style='color:#64748b'>({len(active)})</span>")
        self.k_used.setText(f"<span style='color:#64748b'>{t('Utilisé ce mois')}</span><br><b style='font-size:18px;color:#15803d'>{format_money(AvoirService.redeemed_since(month), cur)}</b>")
        self.k_soon.setText(f"<span style='color:#64748b'>{t('Expire bientôt')}</span><br><b style='font-size:18px'>{len(soon)}</b>")
        needle = self.search.text().strip().lower()
        statuses = _FILTER_STATUSES.get(self._filter)
        rows = []
        for a in everything:
            if statuses and a.status not in statuses:
                continue
            if needle and needle not in self._name(a).lower() and needle not in str(a.id) and needle not in (a.reason or '').lower():
                continue
            rows.append(a)
        keep = self._current_id()
        self._rows = rows
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            late = a.status in (STATUS_CANCELLED, STATUS_EXPIRED)
            vals = [_cell(str(a.id)), _cell(self._name(a)), _cell(format_money(a.amount_remaining, cur), True, '#64748b' if late else None),
                    _cell(t(STATUS_LABELS.get(a.status, a.status)), color='#64748b' if late else None)]
            for c, it in enumerate(vals):
                self.table.setItem(r, c, it)
        self.table.blockSignals(False)
        ids = [a.id for a in rows]
        if keep in ids:
            self.table.setCurrentCell(ids.index(keep), 0)
        self._show()

    def _current_id(self) -> Optional[int]:
        r = self.table.currentRow()
        return self._rows[r].id if 0 <= r < len(self._rows) else None

    _selected_id = _current_id

    def _show(self) -> None:
        a = next((x for x in self._rows if x.id == self._current_id()), None)
        for b in (self.use_button, self.card_button, self.cancel_button):
            b.setEnabled(bool(a))
        if not a:
            self.d_head.setText(t('Sélectionnez un avoir.'))
            self.d_info.setText('')
            self.d_uses.setText('')
            return
        cur = settings_service.get_currency()
        created = a.created_at.strftime('%d/%m/%Y') if getattr(a, 'created_at', None) else ''
        exp = f" · {t('expire le')} {a.expires_on:%d/%m/%Y}" if a.expires_on else ''
        self.d_head.setText(f"<b style='font-size:17px'>{t('Avoir n°')} {a.id} · {self._name(a)}</b><br><span style='color:#64748b'>{a.reason or '—'} · {t('créé le')} {created}{exp}</span>")
        used = float(a.amount_initial) - float(a.amount_remaining)
        self.d_info.setText(f"<table cellspacing='10'><tr><td><span style='color:#64748b'>{t('Montant')}</span><br><b>{format_money(a.amount_initial, cur)}</b></td>"
                            f"<td><span style='color:#64748b'>{t('Reste')}</span><br><b style='color:#15803d'>{format_money(a.amount_remaining, cur)}</b></td>"
                            f"<td><span style='color:#64748b'>{t('Utilisé')}</span><br><b>{format_money(used, cur)}</b></td></tr></table>")
        uses = AvoirService.redemptions(a.id)
        lines = []
        for u in uses[:6]:
            sale = ''
            if u.sale_id:
                from app.controllers.sale_controller import SaleController
                s = SaleController.get(u.sale_id)
                sale = f" · {t('vente')} {s.ticket_number}" if s else ''
            lines.append(f"{u.created_at:%d/%m/%Y} · {format_money(u.amount, cur)}{sale}" + (f" · {u.note}" if u.note else ''))
        self.d_uses.setText(("<span style='color:#64748b'>" + t('Utilisations') + '</span><br>' + '<br>'.join(lines)) if lines else "<span style='color:#64748b'>" + t("Jamais utilisé pour l'instant") + '</span>')
        self.use_button.setEnabled(a.status in (STATUS_ACTIVE, STATUS_PARTIAL))
        self.cancel_button.setEnabled(a.status in (STATUS_ACTIVE, STATUS_PARTIAL))
        self.card_button.setEnabled(bool(a.client_id))

    # ---- actions --------------------------------------------------------------------------
    def _create(self) -> None:
        dlg = NewAvoirDialog(self)
        if not dlg.exec():
            return
        v = dlg.values()
        try:
            AvoirService.create(amount=v['amount'], customer_name=v['customer_name'], client_id=v['client_id'], reason=v['reason'],
                                expires_on=v['expires_on'], created_by=getattr(getattr(self.state, 'current_user', None), 'id', None))
        except Exception as exc:
            warn(self, str(exc))
            return
        self._set_filter('active')
        info(self, t('Avoir créé.'))

    def _redeem_selected(self) -> None:
        avoir_id = self._current_id()
        avoir = AvoirService.get(avoir_id) if avoir_id else None
        if not avoir:
            warn(self, t('Sélectionnez un avoir.'))
            return
        remaining = float(avoir.amount_remaining)
        if remaining <= 0 or not avoir.is_active:
            warn(self, t('Plus rien à utiliser sur cet avoir.'))
            return
        dlg = UseAvoirDialog(remaining, self)
        if not dlg.exec():
            return
        try:
            AvoirService.redeem(avoir_id, float(dlg.amount.value()), note=dlg.note.text().strip() or 'Utilisation manuelle')
        except Exception as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _open_card(self) -> None:
        a = next((x for x in self._rows if x.id == self._current_id()), None)
        if a and a.client_id and self.on_open_client:
            self.on_open_client(a.client_id)

    def _cancel_selected(self) -> None:
        rows = selected_rows(self.table)
        if len(rows) > 1:
            items = [(self._rows[r].id, str(self._rows[r].id)) for r in rows]
            if run_batch(self, t("Annuler {n} avoirs ?"), items, AvoirService.cancel, t("avoir(s) annulé(s)")):
                self.refresh()
            return
        avoir_id = self._current_id()
        if not avoir_id:
            warn(self, t('Sélectionnez un avoir.'))
            return
        if not confirm(self, t('Annuler cet avoir ?'), t('Avoir')):
            return
        try:
            AvoirService.cancel(avoir_id)
        except Exception as exc:
            warn(self, str(exc))
            return
        self.refresh()
