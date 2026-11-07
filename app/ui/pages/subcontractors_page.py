"""Sous-traitance : contrats par chantier (forfait, retenue), paiements, annuaire des sous-traitants."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)
from sqlalchemy import select

from app.database.connection import session_scope
from app.i18n import t
from app.models.chantier import MARKET_STATUSES, Chantier
from app.models.subcontract import RETENTION_RELEASE, SUB_CANCELLED, SUB_DONE, SUB_PAYMENT_KINDS, SUB_RUNNING, SUB_STATUS_LABELS
from app.services import audit_service, permissions as perms, settings_service, subcontract_service as ss
from app.ui.dialogs.chantier_dialog import _money
from app.ui.pages.rentals_page import _cell, _date_edit, _table
from app.ui.state import AppState
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.utils.helpers import format_money


class SubcontractorDialog(QDialog):
    def __init__(self, parent=None, row=None):
        super().__init__(parent)
        self.setWindowTitle(t("Sous-traitant"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=420, min_height=380, preferred_width=500, preferred_height=460)
        form = QFormLayout(self)
        self.name = QLineEdit(row.name if row else "")
        self.trade = QLineEdit(row.trade if row else "")
        self.trade.setPlaceholderText(t("Électricien, plombier, carreleur, peintre…"))
        self.phone = QLineEdit(row.phone if row else "")
        self.address = QLineEdit(row.address if row else "")
        self.tax_id = QLineEdit(row.tax_id if row else "")
        self.tax_id.setPlaceholderText(t("IFU / RCCM"))
        self.active = QCheckBox(t("Actif"))
        self.active.setChecked(row.active if row else True)
        for label, w in ((t("Nom / entreprise"), self.name), (t("Métier"), self.trade), (t("Téléphone"), self.phone),
                         (t("Adresse"), self.address), (t("IFU / RCCM"), self.tax_id)):
            form.addRow(label, w)
        form.addRow("", self.active)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict:
        return dict(name=self.name.text(), trade=self.trade.text(), phone=self.phone.text(), address=self.address.text(),
                    tax_id=self.tax_id.text(), active=self.active.isChecked())


class SubcontractDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Nouveau contrat de sous-traitance"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=460, min_height=420, preferred_width=560, preferred_height=520)
        form = QFormLayout(self)
        self.chantier = QComboBox()
        with session_scope() as session:
            for c in session.scalars(select(Chantier).where(Chantier.status.in_(MARKET_STATUSES)).order_by(Chantier.name)):
                self.chantier.addItem(f"{c.number} — {c.name}", c.id)
        self.sub = QComboBox()
        for x in ss.list_subcontractors():
            self.sub.addItem(f"{x.name} ({x.trade})" if x.trade else x.name, x.id)
        self.label = QLineEdit()
        self.label.setPlaceholderText(t("Ex. Électricité du bâtiment A (lot 4)"))
        self.amount = _money()
        self.retention = _money()
        self.retention.setDecimals(1)
        self.retention.setSuffix(" %")
        self.retention.setMaximum(30)
        self.end = QDateEdit(QDate.currentDate().addDays(30))
        self.end.setCalendarPopup(True)
        self.end.setDisplayFormat("dd/MM/yyyy")
        self.has_end = QCheckBox(t("Date de fin prévue"))
        self.has_end.setChecked(True)
        for lab, w in ((t("Chantier"), self.chantier), (t("Sous-traitant"), self.sub), (t("Travail confié"), self.label),
                       (t("Montant du forfait"), self.amount), (t("Retenue de garantie"), self.retention)):
            form.addRow(lab, w)
        form.addRow(self.has_end, self.end)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict:
        d = self.end.date()
        return dict(chantier_id=self.chantier.currentData(), subcontractor_id=self.sub.currentData(), label=self.label.text(),
                    amount=self.amount.value(), retention_pct=self.retention.value(),
                    end_planned=datetime(d.year(), d.month(), d.day()) if self.has_end.isChecked() else None)


class SubcontractorsPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.can_manage = state.can(perms.MANAGE_SUBCONTRACTORS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(page_title(t("Sous-traitants")))
        self.banner = QLabel()
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        self.banner.setWordWrap(True)
        layout.addWidget(make_card(self.banner))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_contracts(), t("Contrats"))
        self.tabs.addTab(self._build_directory(), t("Annuaire"))

    def _user(self):
        return self.state.user_id, getattr(self.state.current_user, "username", "")

    def _cur(self) -> str:
        return settings_service.get_shop_info().currency or "FCFA"

    # -- contrats -------------------------------------------------------------------------------
    def _build_contracts(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.f_chantier = QComboBox()
        self.f_chantier.currentIndexChanged.connect(self.refresh)
        new = QPushButton(t("+ Nouveau contrat"))
        new.setObjectName("Primary")
        new.setEnabled(self.can_manage)
        new.clicked.connect(self._new_contract)
        bar.addWidget(QLabel(t("Chantier")))
        bar.addWidget(self.f_chantier, 1)
        bar.addWidget(new)
        lay.addLayout(bar)
        self.contracts = _table(["N°", "Chantier", "Sous-traitant", "Travail", "Statut", "Forfait", "Payé", "Reste à payer", "Retenue détenue", "Fin prévue"])
        self.contracts.currentCellChanged.connect(lambda *_: self._refresh_payments())
        lay.addWidget(self.contracts, 2)
        lay.addWidget(QLabel(f"<b>{t('Paiements du contrat sélectionné')}</b>"))
        self.payments = _table(["Date", "Type", "Montant", "Référence"])
        lay.addWidget(self.payments, 1)
        row = QHBoxLayout()
        self.btn_pay = QPushButton(t("Payer"))
        self.btn_pay.setObjectName("Primary")
        self.btn_done = QPushButton(t("Travaux réceptionnés"))
        self.btn_cancel = QPushButton(t("Annuler le contrat"))
        self.btn_pdf = QPushButton(t("Contrat + situation (PDF)"))
        self.btn_rm_pay = QPushButton(t("Supprimer le paiement"))
        self.btn_rm_pay.setObjectName("Danger")
        self.btn_pay.clicked.connect(self._pay)
        self.btn_done.clicked.connect(lambda: self._status(SUB_DONE))
        self.btn_cancel.clicked.connect(lambda: self._status(SUB_CANCELLED))
        self.btn_pdf.clicked.connect(self._pdf)
        self.btn_rm_pay.clicked.connect(self._delete_payment)
        for b in (self.btn_pay, self.btn_done, self.btn_cancel, self.btn_rm_pay):
            b.setEnabled(self.can_manage)
            row.addWidget(b)
        row.insertWidget(3, self.btn_pdf)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _sid(self):
        r = self.contracts.currentRow()
        return self.contracts.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def _new_contract(self) -> None:
        dlg = SubcontractDialog(self)
        if dlg.chantier.count() == 0 or dlg.sub.count() == 0:
            warn(self, t("Il faut au moins un chantier en cours et un sous-traitant (onglet Annuaire)."))
            return
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            sid = ss.create_subcontract(user_id=self.state.user_id, **dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Contrat sous-traitance", "Subcontract", str(sid), *self._user())
        self.refresh()

    def _pay(self) -> None:
        sid = self._sid()
        if not sid:
            return
        s = ss.summary(sid)
        kind, ok = QInputDialog.getItem(self, t("Payer"), t("Type de paiement"), [t(k) for k in SUB_PAYMENT_KINDS], 0, False)
        if not ok:
            return
        kind = SUB_PAYMENT_KINDS[[t(k) for k in SUB_PAYMENT_KINDS].index(kind)]
        default = s.retention_held if kind == RETENTION_RELEASE else s.payable_now
        value, ok = QInputDialog.getDouble(self, t("Payer"), f"{t('Montant')} ({kind})", default, 0, 1e10, 0)
        if not ok or value <= 0:
            return
        ref, _ = QInputDialog.getText(self, t("Payer"), t("Référence (n° de chèque, reçu…) — facultatif"))
        try:
            ss.add_payment(sid, value, kind=kind, reference=ref, user_id=self.state.user_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Paiement sous-traitant", "Subcontract", s.number, *self._user())
        self.state.notify_data_changed()
        self.refresh()

    def _status(self, status: str) -> None:
        sid = self._sid()
        if not sid:
            return
        msg = t("Confirmer la réception des travaux ?") if status == SUB_DONE else t("Annuler ce contrat ?")
        if confirm(self, msg):
            ss.set_status(sid, status)
            self.refresh()

    def _delete_payment(self) -> None:
        r = self.payments.currentRow()
        if r < 0:
            return
        if confirm(self, t("Supprimer ce paiement ? La dépense du chantier est retirée aussi.")):
            ss.delete_payment(self.payments.item(r, 0).data(Qt.ItemDataRole.UserRole))
            self.state.notify_data_changed()
            self.refresh()

    def _pdf(self) -> None:
        sid = self._sid()
        if not sid:
            return
        from app.printers import subcontract_docs
        path = Path(tempfile.gettempdir()) / f"sous_traitance_{sid}.pdf"
        subcontract_docs.build_contract(sid, path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # -- annuaire ----------------------------------------------------------------------------------
    def _build_directory(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.directory = _table(["Nom", "Métier", "Téléphone", "IFU / RCCM", "Contrats", "Reste à payer", "Actif"])
        lay.addWidget(self.directory, 1)
        row = QHBoxLayout()
        add = QPushButton(t("+ Ajouter un sous-traitant"))
        add.setObjectName("Primary")
        edit = QPushButton(t("Modifier"))
        rm = QPushButton(t("Supprimer"))
        rm.setObjectName("Danger")
        add.clicked.connect(lambda: self._dir_dialog(None))
        edit.clicked.connect(lambda: self._dir_dialog(self._dir_current()))
        rm.clicked.connect(self._dir_delete)
        for b in (add, edit, rm):
            b.setEnabled(self.can_manage)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _dir_current(self):
        r = self.directory.currentRow()
        if r < 0:
            return None
        sid = self.directory.item(r, 0).data(Qt.ItemDataRole.UserRole)
        return next((x for x in ss.list_subcontractors(True) if x.id == sid), None)

    def _dir_dialog(self, row) -> None:
        dlg = SubcontractorDialog(self, row)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            ss.save_subcontractor(subcontractor_id=row.id if row else None, **dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _dir_delete(self) -> None:
        row = self._dir_current()
        if row and confirm(self, t("Supprimer ce sous-traitant ?")):
            try:
                ss.delete_subcontractor(row.id)
            except ValueError as exc:
                warn(self, str(exc))
                return
            self.refresh()

    # -- affichage -----------------------------------------------------------------------------------
    def refresh(self, *_a) -> None:
        cur = self._cur()
        current = self.f_chantier.currentData()
        self.f_chantier.blockSignals(True)
        self.f_chantier.clear()
        self.f_chantier.addItem(t("Tous les chantiers"), None)
        with session_scope() as session:
            for c in session.scalars(select(Chantier).where(Chantier.status.in_(MARKET_STATUSES)).order_by(Chantier.name)):
                self.f_chantier.addItem(f"{c.number} — {c.name}", c.id)
        idx = self.f_chantier.findData(current)
        self.f_chantier.setCurrentIndex(max(0, idx))
        self.f_chantier.blockSignals(False)
        rows = ss.list_subcontracts(self.f_chantier.currentData())
        self.contracts.setRowCount(len(rows))
        for r, s in enumerate(rows):
            end = s.end_planned.strftime("%d/%m/%Y") if s.end_planned else ""
            cells = [s.number, s.chantier, s.subcontractor, s.label, t(SUB_STATUS_LABELS[s.status]), format_money(s.amount, cur), format_money(s.paid, cur),
                     format_money(s.payable_now, cur), format_money(s.retention_held, cur), end + (f" ({t('en retard')})" if s.late else "")]
            for c, v in enumerate(cells):
                self.contracts.setItem(r, c, _cell(v, 5 <= c <= 8, s.id if c == 0 else None, "#b91c1c" if (s.late and c == 9) else None))
            if s.alerts:
                self.contracts.item(r, 3).setToolTip("\n".join(s.alerts))
        self._refresh_payments()
        everything = ss.list_subcontracts()
        live = [s for s in everything if s.status != SUB_CANCELLED]
        parts = [f"<b>{t('Reste à payer')}</b> : {format_money(sum(s.payable_now for s in live), cur)}",
                 f"<b>{t('Retenues détenues')}</b> : {format_money(sum(s.retention_held for s in live), cur)}"]
        late = [s for s in live if s.late]
        release = [s for s in live if s.status == SUB_DONE and s.retention_held > 0]
        if late:
            parts.append(f"<span style='color:#b91c1c'>{len(late)} {t('contrat(s) en retard')}</span>")
        if release:
            parts.append(f"<span style='color:#b45309'>{len(release)} {t('retenue(s) à libérer après réception')}</span>")
        self.banner.setText(" &nbsp;·&nbsp; ".join(parts))
        subs = ss.list_subcontractors(True)
        self.directory.setRowCount(len(subs))
        for r, x in enumerate(subs):
            mine = [s for s in live if s.subcontractor == x.name]
            cells = [x.name, x.trade, x.phone, x.tax_id, len(mine), format_money(sum(s.payable_now for s in mine), cur), t("Oui") if x.active else t("Non")]
            for c, v in enumerate(cells):
                self.directory.setItem(r, c, _cell(v, c in (4, 5), x.id if c == 0 else None))

    def _refresh_payments(self) -> None:
        sid = self._sid()
        pays = ss.list_payments(sid) if sid else []
        cur = self._cur()
        self.payments.setRowCount(len(pays))
        for r, p in enumerate(pays):
            for c, v in enumerate([p.date.strftime("%d/%m/%Y"), t(p.kind), format_money(float(p.amount), cur), p.reference]):
                self.payments.setItem(r, c, _cell(v, c == 2, p.id if c == 0 else None))
