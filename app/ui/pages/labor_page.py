"""Main-d'œuvre : ouvriers, pointage par chantier, avances et paie (la paie devient une dépense du chantier)."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)
from sqlalchemy import select

from app.database.connection import session_scope
from app.i18n import t
from app.models.chantier import MARKET_STATUSES, Chantier
from app.services import audit_service, labor_service as ls, permissions as perms, settings_service
from app.ui.pages.rentals_page import _cell, _date_edit, _table
from app.ui.dialogs.chantier_dialog import _money
from app.ui.state import AppState
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.utils.helpers import format_money


class WorkerDialog(QDialog):
    def __init__(self, parent=None, worker=None):
        super().__init__(parent)
        self.setWindowTitle(t("Ouvrier"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=400, min_height=300, preferred_width=480, preferred_height=360)
        form = QFormLayout(self)
        self.name = QLineEdit(worker.name if worker else "")
        self.trade = QLineEdit(worker.trade if worker else "")
        self.trade.setPlaceholderText(t("Maçon, soudeur, menuisier, manœuvre…"))
        self.phone = QLineEdit(worker.phone if worker else "")
        self.rate = _money()
        self.rate.setValue(float(worker.daily_rate) if worker else 0)
        self.active = QCheckBox(t("Actif"))
        self.active.setChecked(worker.active if worker else True)
        form.addRow(t("Nom"), self.name)
        form.addRow(t("Métier"), self.trade)
        form.addRow(t("Téléphone"), self.phone)
        form.addRow(t("Tarif par jour"), self.rate)
        form.addRow("", self.active)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict:
        return dict(name=self.name.text(), trade=self.trade.text(), phone=self.phone.text(), daily_rate=self.rate.value(), active=self.active.isChecked())


class LaborPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.can_manage = state.can(perms.MANAGE_LABOR)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(page_title(t("Main-d'œuvre")))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_clock(), t("Pointage"))
        self.tabs.addTab(self._build_payroll(), t("Paie"))
        self.tabs.addTab(self._build_workers(), t("Ouvriers"))

    def _user(self):
        return self.state.user_id, getattr(self.state.current_user, "username", "")

    def _cur(self) -> str:
        return settings_service.get_shop_info().currency or "FCFA"

    # -- ouvriers ----------------------------------------------------------------------
    def _build_workers(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.workers = _table(["Nom", "Métier", "Téléphone", "Tarif / jour", "Avances à déduire", "Actif"])
        lay.addWidget(self.workers, 1)
        row = QHBoxLayout()
        add = QPushButton(t("+ Ajouter un ouvrier"))
        add.setObjectName("Primary")
        edit = QPushButton(t("Modifier"))
        adv = QPushButton(t("Donner une avance"))
        rm = QPushButton(t("Supprimer"))
        rm.setObjectName("Danger")
        add.clicked.connect(lambda: self._worker_dialog(None))
        edit.clicked.connect(lambda: self._worker_dialog(self._current_worker()))
        adv.clicked.connect(self._advance)
        rm.clicked.connect(self._worker_delete)
        for b in (add, edit, adv, rm):
            b.setEnabled(self.can_manage)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _current_worker(self):
        r = self.workers.currentRow()
        if r < 0:
            return None
        wid = self.workers.item(r, 0).data(Qt.ItemDataRole.UserRole)
        return next((x for x in ls.list_workers(True) if x.id == wid), None)

    def _worker_dialog(self, worker) -> None:
        dlg = WorkerDialog(self, worker)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            ls.save_worker(worker_id=worker.id if worker else None, **dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _worker_delete(self) -> None:
        w = self._current_worker()
        if w and confirm(self, t("Supprimer cet ouvrier ?")):
            try:
                ls.delete_worker(w.id)
            except ValueError as exc:
                warn(self, str(exc))
                return
            self.refresh()

    def _advance(self) -> None:
        w = self._current_worker()
        if not w:
            return
        value, ok = QInputDialog.getDouble(self, t("Avance"), f"{t('Montant donné à')} {w.name}", 0, 0, 1e10, 0)
        if ok and value > 0:
            ls.add_advance(w.id, value)
            audit_service.log_action("Avance ouvrier", "Worker", w.name, *self._user())
            self.refresh()

    # -- pointage ------------------------------------------------------------------------------
    def _build_clock(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QHBoxLayout()
        self.cw = QComboBox()
        self.cc = QComboBox()
        self.cdate = _date_edit()
        self.cdays = QComboBox()
        for label, v in ((t("1 jour"), 1.0), (t("½ jour"), 0.5)):
            self.cdays.addItem(label, v)
        add = QPushButton(t("Pointer"))
        add.setObjectName("Primary")
        add.setEnabled(self.can_manage)
        add.clicked.connect(self._clock)
        for lab, wd in ((t("Ouvrier"), self.cw), (t("Chantier"), self.cc), (t("Date"), self.cdate), (t("Durée"), self.cdays)):
            form.addWidget(QLabel(lab))
            form.addWidget(wd, 1 if wd in (self.cw, self.cc) else 0)
        form.addWidget(add)
        lay.addLayout(form)
        self.days = _table(["Date", "Ouvrier", "Chantier", "Jours", "Tarif", "Montant", "Payé"])
        lay.addWidget(self.days, 1)
        row = QHBoxLayout()
        rm = QPushButton(t("Supprimer le pointage"))
        rm.setObjectName("Danger")
        rm.setEnabled(self.can_manage)
        rm.clicked.connect(self._unclock)
        row.addWidget(rm)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _clock(self) -> None:
        wid, cid = self.cw.currentData(), self.cc.currentData()
        if not wid or not cid:
            warn(self, t("Ajoutez un ouvrier et un chantier en cours d'abord."))
            return
        d = self.cdate.date()
        try:
            ls.clock_in(wid, cid, date=datetime(d.year(), d.month(), d.day()), days=self.cdays.currentData())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _unclock(self) -> None:
        r = self.days.currentRow()
        if r < 0:
            return
        try:
            ls.delete_day(self.days.item(r, 0).data(Qt.ItemDataRole.UserRole))
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    # -- paie -------------------------------------------------------------------------------------
    def _build_payroll(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.p_start = _date_edit(-6)
        self.p_end = _date_edit(0)
        for lab, wd in ((t("Du"), self.p_start), (t("Au"), self.p_end)):
            bar.addWidget(QLabel(lab))
            bar.addWidget(wd)
        self.p_all = QCheckBox(t("Tout ce qui n'est pas payé"))
        self.p_all.setChecked(True)
        bar.addWidget(self.p_all)
        bar.addStretch()
        lay.addLayout(bar)
        self.payroll = _table(["Ouvrier", "Jours", "Brut", "Avances déduites", "Net à verser"])
        lay.addWidget(self.payroll, 1)
        self.p_total = QLabel()
        lay.addWidget(self.p_total)
        row = QHBoxLayout()
        pay = QPushButton(t("Payer l'ouvrier sélectionné"))
        pay.setObjectName("Primary")
        pay.setEnabled(self.can_manage)
        pay.clicked.connect(self._pay)
        row.addWidget(pay)
        row.addStretch()
        lay.addLayout(row)
        self.p_all.toggled.connect(self.refresh)
        self.p_start.dateChanged.connect(self.refresh)
        self.p_end.dateChanged.connect(self.refresh)
        return w

    def _period(self):
        if self.p_all.isChecked():
            return None, None
        a, b = self.p_start.date(), self.p_end.date()
        from datetime import timedelta
        return datetime(a.year(), a.month(), a.day()), datetime(b.year(), b.month(), b.day()) + timedelta(days=1)

    def _pay(self) -> None:
        r = self.payroll.currentRow()
        if r < 0:
            return
        wid = self.payroll.item(r, 0).data(Qt.ItemDataRole.UserRole)
        name, net = self.payroll.item(r, 0).text(), self.payroll.item(r, 4).text()
        if not confirm(self, f"{t('Payer')} {name} : {net} ?\n{t('Le coût est ajouté aux dépenses des chantiers concernés.')}"):
            return
        start, end = self._period()
        try:
            ls.pay_worker(wid, start=start, end=end, user_id=self.state.user_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Paie ouvrier", "Worker", name, *self._user())
        self.state.data_changed.emit()
        self.refresh()

    # -- affichage -----------------------------------------------------------------------------------
    def refresh(self, *_a) -> None:
        cur = self._cur()
        self.cw.clear()
        for x in ls.list_workers():
            self.cw.addItem(f"{x.name} — {format_money(float(x.daily_rate), cur)}/j", x.id)
        self.cc.clear()
        with session_scope() as session:
            for c in session.scalars(select(Chantier).where(Chantier.status.in_(MARKET_STATUSES)).order_by(Chantier.name)):
                self.cc.addItem(f"{c.number} — {c.name}", c.id)
        days = ls.list_days()
        self.days.setRowCount(len(days))
        for r, d in enumerate(days):
            cells = [d.date.strftime("%d/%m/%Y"), d.worker, d.chantier, f"{d.days:g}", format_money(d.rate, cur), format_money(d.amount, cur), t("Oui") if d.paid else ""]
            for c, v in enumerate(cells):
                self.days.setItem(r, c, _cell(v, c in (3, 4, 5), d.id if c == 0 else None))
        workers = ls.list_workers(True)
        self.workers.setRowCount(len(workers))
        for r, x in enumerate(workers):
            cells = [x.name, x.trade, x.phone, format_money(float(x.daily_rate), cur), format_money(ls.advances_due(x.id), cur), t("Oui") if x.active else t("Non")]
            for c, v in enumerate(cells):
                self.workers.setItem(r, c, _cell(v, c in (3, 4), x.id if c == 0 else None))
        start, end = self._period()
        lines = ls.payroll_preview(start, end)
        self.payroll.setRowCount(len(lines))
        for r, l in enumerate(lines):
            cells = [l.worker, f"{l.days:g}", format_money(l.gross, cur), format_money(l.advances, cur), format_money(l.net, cur)]
            for c, v in enumerate(cells):
                self.payroll.setItem(r, c, _cell(v, c > 0, l.worker_id if c == 0 else None))
        self.p_total.setText(f"<b>{t('Total à verser')}</b> : {format_money(sum(l.net for l in lines), cur)} &nbsp;·&nbsp; {t('Coût brut')} : {format_money(sum(l.gross for l in lines), cur)}")
