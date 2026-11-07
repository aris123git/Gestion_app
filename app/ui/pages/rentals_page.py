"""Location de matériel : contrats en cours / rendus, retour, encaissement, parc."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from app.controllers.client_controller import ClientController
from app.i18n import t
from app.models.rental import CONDITIONS, RENTAL_OUT, RENTAL_RETURNED
from app.services import audit_service, permissions as perms, rental_service as rs, settings_service
from app.ui.dialogs.chantier_dialog import _money
from app.ui.state import AppState
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.utils.helpers import format_money


def _table(headers, stretch=0) -> QTableWidget:
    tb = QTableWidget(0, len(headers))
    tb.setHorizontalHeaderLabels([t(h) for h in headers])
    tb.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    tb.horizontalHeader().setStretchLastSection(True)
    tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tb.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tb.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    return tb


def _cell(text, right=False, data=None, color=None) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    if right:
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if data is not None:
        it.setData(Qt.ItemDataRole.UserRole, data)
    if color:
        it.setForeground(QColor(color))
    return it


def _qdate_to_dt(edit: QDateEdit, end_of_day: bool = False) -> datetime:
    d = edit.date()
    return datetime(d.year(), d.month(), d.day(), 18 if end_of_day else datetime.now().hour, 0 if end_of_day else datetime.now().minute)


def _date_edit(days: int = 0) -> QDateEdit:
    e = QDateEdit(QDate.currentDate().addDays(days))
    e.setCalendarPopup(True)
    e.setDisplayFormat("dd/MM/yyyy")
    return e


class ItemDialog(QDialog):
    def __init__(self, parent=None, item=None):
        super().__init__(parent)
        self.setWindowTitle(t("Matériel du parc"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=420, min_height=420, preferred_width=520, preferred_height=560)
        form = QFormLayout(self)
        self.name = QLineEdit(item.name if item else "")
        self.category = QLineEdit(item.category if item else "")
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 9999)
        self.quantity.setValue(item.quantity if item else 1)
        self.rate = _money()
        self.rate.setValue(item.rate_day if item else 0)
        self.deposit = _money()
        self.deposit.setValue(item.deposit if item else 0)
        self.condition = QComboBox()
        self.condition.addItems([t(c) for c in CONDITIONS])
        self.service = QSpinBox()
        self.service.setRange(0, 9999)
        self.service.setSpecialValueText(t("Non suivi"))
        self.service.setSuffix(" " + t("jours"))
        self.active = QCheckBox(t("Disponible à la location"))
        self.active.setChecked(item.active if item else True)
        form.addRow(t("Nom"), self.name)
        form.addRow(t("Catégorie"), self.category)
        form.addRow(t("Quantité en parc"), self.quantity)
        form.addRow(t("Prix par jour"), self.rate)
        form.addRow(t("Caution par unité"), self.deposit)
        form.addRow(t("État"), self.condition)
        form.addRow(t("Révision tous les"), self.service)
        form.addRow("", self.active)
        if item:
            idx = CONDITIONS.index(item.condition) if item.condition in CONDITIONS else 0
            self.condition.setCurrentIndex(idx)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict:
        return dict(name=self.name.text(), category=self.category.text(), quantity=self.quantity.value(), rate_day=self.rate.value(),
                    deposit=self.deposit.value(), condition=CONDITIONS[self.condition.currentIndex()], service_every_days=self.service.value(),
                    active=self.active.isChecked())


class NewRentalDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Nouvelle location"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=560, min_height=560, preferred_width=680, preferred_height=700)
        self.items = [i for i in rs.list_items() if i.available > 0]
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.client = QComboBox()
        self.client.setEditable(True)
        self.client.addItem("", None)
        for c in ClientController.list():
            self.client.addItem(c.name, c.id)
        self.client.setCurrentIndex(0)
        self.phone = QLineEdit()
        self.id_doc = QLineEdit()
        self.id_doc.setPlaceholderText(t("Ex. CNIB n° … (pièce gardée en garantie)"))
        self.start = _date_edit()
        self.due = _date_edit(3)
        form.addRow(t("Client"), self.client)
        form.addRow(t("Téléphone"), self.phone)
        form.addRow(t("Pièce d'identité remise"), self.id_doc)
        form.addRow(t("Départ"), self.start)
        form.addRow(t("Retour prévu le"), self.due)
        root.addLayout(form)
        root.addWidget(QLabel(f"<b>{t('Matériel loué')}</b>"))
        self.rows = QTableWidget(0, 3)
        self.rows.setHorizontalHeaderLabels([t("Matériel"), t("Quantité"), t("Prix / jour")])
        self.rows.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.rows.setMinimumHeight(150)
        root.addWidget(self.rows)
        add = QPushButton(t("+ Ajouter un matériel"))
        add.clicked.connect(self._add_row)
        root.addWidget(add)
        form2 = QFormLayout()
        self.deposit = _money()
        self.paid = _money()
        self.deposit_auto = QCheckBox(t("Caution calculée d'après le parc"))
        self.deposit_auto.setChecked(True)
        self.deposit_auto.toggled.connect(lambda on: self.deposit.setEnabled(not on))
        self.deposit.setEnabled(False)
        self.out_cond = QLineEdit()
        self.out_cond.setPlaceholderText(t("État du matériel au départ"))
        form2.addRow("", self.deposit_auto)
        form2.addRow(t("Caution reçue"), self.deposit)
        form2.addRow(t("Loyer payé d'avance"), self.paid)
        form2.addRow(t("État au départ"), self.out_cond)
        root.addLayout(form2)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self._add_row()

    def _add_row(self) -> None:
        if not self.items:
            warn(self, t("Aucun matériel disponible : ajoutez du matériel au parc."))
            return
        r = self.rows.rowCount()
        self.rows.insertRow(r)
        combo = QComboBox()
        for i in self.items:
            combo.addItem(f"{i.name} ({i.available} {t('dispo')})", i.id)
        qty = QSpinBox()
        qty.setRange(1, 9999)
        rate = _money()
        rate.setValue(self.items[0].rate_day)
        combo.currentIndexChanged.connect(lambda _i, c=combo, rt=rate: rt.setValue(next(x.rate_day for x in self.items if x.id == c.currentData())))
        self.rows.setCellWidget(r, 0, combo)
        self.rows.setCellWidget(r, 1, qty)
        self.rows.setCellWidget(r, 2, rate)

    def values(self) -> dict:
        text = self.client.currentText().strip()
        cid = self.client.currentData() if text and self.client.findText(text) >= 0 else None
        lines = [rs.LineInput(self.rows.cellWidget(r, 0).currentData(), self.rows.cellWidget(r, 1).value(), self.rows.cellWidget(r, 2).value())
                 for r in range(self.rows.rowCount())]
        return dict(client_label=text, client_id=cid, phone=self.phone.text(), id_document=self.id_doc.text(), start_date=_qdate_to_dt(self.start),
                    due_date=_qdate_to_dt(self.due, True), lines=lines, deposit=None if self.deposit_auto.isChecked() else self.deposit.value(),
                    paid=self.paid.value(), out_condition=self.out_cond.text())


class ReturnDialog(QDialog):
    def __init__(self, parent, s, currency: str):
        super().__init__(parent)
        self.setWindowTitle(t("Retour du matériel"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=460, min_height=360, preferred_width=520, preferred_height=440)
        form = QFormLayout(self)
        form.addRow(QLabel(f"<b>{s.number}</b> — {s.client}<br/>{s.items}"))
        self.when = _date_edit()
        self.damage = _money()
        self.condition = QLineEdit()
        self.condition.setPlaceholderText(t("État au retour, pièces manquantes…"))
        form.addRow(t("Date de retour"), self.when)
        form.addRow(t("Dégâts / pièces manquantes à facturer"), self.damage)
        form.addRow(t("État au retour"), self.condition)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        form.addRow(self.hint)
        self._s, self._cur = s, currency
        self.when.dateChanged.connect(self._update)
        self.damage.valueChanged.connect(self._update)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self._update()

    def _update(self, *_a) -> None:
        s = self._s
        per_day = s.base / s.days_planned if s.days_planned else 0
        when = _qdate_to_dt(self.when, True)
        late_days = max(0, (when.date() - s.due_date.date()).days)
        late = per_day * late_days * rs.late_multiplier()
        total = s.base + late + self.damage.value()
        owed = max(0.0, total - s.paid)
        refund = max(0.0, s.deposit - owed)
        extra = max(0.0, owed - s.deposit)
        text = (f"{t('Loyer')} {format_money(s.base, self._cur)} + {t('retard')} ({late_days} j) {format_money(late, self._cur)} + {t('dégâts')} "
                f"{format_money(self.damage.value(), self._cur)} = <b>{format_money(total, self._cur)}</b><br/>{t('Déjà payé')} : {format_money(s.paid, self._cur)} · "
                f"{t('Caution')} : {format_money(s.deposit, self._cur)}<br/>")
        text += (f"<b>{t('À rendre au client')} : {format_money(refund, self._cur)}</b>" if not extra
                 else f"<b style='color:#b91c1c'>{t('Reste à encaisser')} : {format_money(extra, self._cur)}</b>")
        self.hint.setText(text)

    def values(self) -> dict:
        return dict(returned_at=_qdate_to_dt(self.when, True), damage_fee=self.damage.value(), return_condition=self.condition.text())


class RentalsPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.can_manage = state.can(perms.MANAGE_RENTALS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(page_title(t("Location de matériel")))
        self.banner = QLabel()
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        self.banner.setWordWrap(True)
        self.banner_card = make_card(self.banner)
        layout.addWidget(self.banner_card)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_rentals(), t("Locations"))
        self.tabs.addTab(self._build_park(), t("Parc de matériel"))

    # -- locations -----------------------------------------------------------------
    def _build_rentals(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem(t("Toutes"), None)
        self.filter.addItem(t("En cours"), RENTAL_OUT)
        self.filter.addItem(t("Rendues"), RENTAL_RETURNED)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("Rechercher un client, un matériel, un numéro…"))
        new = QPushButton(t("+ Nouvelle location"))
        new.setObjectName("Primary")
        new.setEnabled(self.can_manage)
        new.clicked.connect(self._new)
        bar.addWidget(self.filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(new)
        lay.addLayout(bar)
        self.table = _table(["N°", "Client", "Matériel", "Départ", "Retour prévu", "Statut", "Total", "Payé", "Reste dû", "Caution"])
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.btn_return = QPushButton(t("Enregistrer le retour"))
        self.btn_return.setObjectName("Primary")
        self.btn_pay = QPushButton(t("Encaisser"))
        self.btn_extend = QPushButton(t("Prolonger"))
        self.btn_pdf = QPushButton(t("Contrat (PDF)"))
        self.btn_del = QPushButton(t("Supprimer"))
        self.btn_del.setObjectName("Danger")
        self.btn_return.clicked.connect(self._return)
        self.btn_pay.clicked.connect(self._pay)
        self.btn_extend.clicked.connect(self._extend)
        self.btn_pdf.clicked.connect(self._pdf)
        self.btn_del.clicked.connect(self._delete)
        for b in (self.btn_return, self.btn_pay, self.btn_extend, self.btn_del):
            b.setEnabled(self.can_manage)
            row.addWidget(b)
        row.addStretch()
        row.insertWidget(4, self.btn_pdf)
        lay.addLayout(row)
        self.filter.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        return w

    def _build_park(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.park = _table(["Matériel", "Catégorie", "En parc", "Sorti", "Disponible", "Prix / jour", "Caution", "État", "Réparations", "Entretien"])
        lay.addWidget(self.park, 1)
        row = QHBoxLayout()
        add = QPushButton(t("+ Ajouter du matériel"))
        add.setObjectName("Primary")
        edit = QPushButton(t("Modifier"))
        repair = QPushButton(t("Réparation / révision"))
        delete = QPushButton(t("Supprimer"))
        delete.setObjectName("Danger")
        add.clicked.connect(lambda: self._item_dialog(None))
        edit.clicked.connect(lambda: self._item_dialog(self._park_current()))
        repair.clicked.connect(self._repair)
        delete.clicked.connect(self._item_delete)
        for b in (add, edit, repair, delete):
            b.setEnabled(self.can_manage)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _user(self):
        return self.state.user_id, getattr(self.state.current_user, "username", "")

    def _cur(self) -> str:
        return settings_service.get_shop_info().currency or "FCFA"

    def _id(self, table=None):
        table = table or self.table
        r = table.currentRow()
        return table.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def _new(self) -> None:
        dlg = NewRentalDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            rid = rs.create_rental(user_id=self.state.user_id, **dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Location créée", "Rental", str(rid), *self._user())
        self.refresh()
        if confirm(self, t("Location enregistrée. Imprimer le contrat ?")):
            self._open_pdf(rid)

    def _return(self) -> None:
        rid = self._id()
        if not rid:
            return
        s = rs.summary(rid)
        if s.status == RENTAL_RETURNED:
            warn(self, t("Cette location est déjà rendue."))
            return
        dlg = ReturnDialog(self, s, self._cur())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            done = rs.return_rental(rid, **dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Retour de location", "Rental", s.number, *self._user())
        msg = t("Retour enregistré.")
        if done.deposit_refunded:
            msg += f" {t('Caution à rendre')} : {format_money(done.deposit_refunded, self._cur())}."
        if done.balance:
            msg += f" {t('Reste à encaisser')} : {format_money(done.balance, self._cur())}."
        info(self, msg)
        self.refresh()

    def _pay(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        rid = self._id()
        if not rid:
            return
        s = rs.summary(rid)
        value, ok = QInputDialog.getDouble(self, t("Encaisser"), f"{t('Reste dû')} : {format_money(s.balance, self._cur())}", s.balance, 0, 1e10, 0)
        if not ok or value <= 0:
            return
        try:
            rs.add_payment(rid, value)
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Encaissement location", "Rental", s.number, *self._user())
        self.refresh()

    def _extend(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        rid = self._id()
        if not rid:
            return
        s = rs.summary(rid)
        days, ok = QInputDialog.getInt(self, t("Prolonger"), t("Nombre de jours en plus :"), 1, 1, 365)
        if not ok:
            return
        from datetime import timedelta
        try:
            rs.update_due_date(rid, s.due_date + timedelta(days=days))
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        rid = self._id()
        if rid and confirm(self, t("Supprimer cette location ?")):
            try:
                rs.delete_rental(rid)
            except ValueError as exc:
                warn(self, str(exc))
                return
            self.refresh()

    def _pdf(self) -> None:
        rid = self._id()
        if rid:
            self._open_pdf(rid)

    def _open_pdf(self, rid: int) -> None:
        from app.printers import rental_docs
        path = Path(tempfile.gettempdir()) / f"contrat_location_{rid}.pdf"
        rental_docs.build_contract(rid, path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # -- parc ------------------------------------------------------------------------------
    def _park_current(self):
        pid = self._id(self.park)
        return next((i for i in rs.list_items(True) if i.id == pid), None) if pid else None

    def _item_dialog(self, item) -> None:
        dlg = ItemDialog(self, item)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            rs.save_item(item_id=item.id if item else None, **dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _repair(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        item = self._park_current()
        if not item:
            return
        cost, ok = QInputDialog.getDouble(self, t("Réparation / révision"), t("Coût (0 si aucun) :"), 0, 0, 1e10, 0)
        if ok:
            rs.record_repair(item.id, cost)
            self.refresh()

    def _item_delete(self) -> None:
        item = self._park_current()
        if item and confirm(self, t("Supprimer ce matériel du parc ?")):
            try:
                rs.delete_item(item.id)
            except ValueError as exc:
                warn(self, str(exc))
                return
            self.refresh()

    # -- affichage ---------------------------------------------------------------------------
    def refresh(self) -> None:
        cur = self._cur()
        rows = rs.list_rentals(self.filter.currentData(), self.search.text())
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            status = t("Rendu") if s.status == RENTAL_RETURNED else (t("EN RETARD") if s.overdue else t("En cours"))
            color = "#b91c1c" if s.overdue else ("#b45309" if s.due_today else None)
            cells = [(s.number, False), (s.client, False), (s.items, False), (s.start_date.strftime("%d/%m/%Y"), False),
                     (s.due_date.strftime("%d/%m/%Y"), False), (status, False), (format_money(s.total, cur), True), (format_money(s.paid, cur), True),
                     (format_money(s.balance, cur), True), (format_money(s.deposit, cur), True)]
            for c, (text, right) in enumerate(cells):
                self.table.setItem(r, c, _cell(text, right, s.id if c == 0 else None, color if c in (4, 5) else None))
            if s.alerts:
                self.table.item(r, 1).setToolTip("\n".join(s.alerts))
        items = rs.list_items(True)
        self.park.setRowCount(len(items))
        for r, i in enumerate(items):
            cells = [i.name, i.category, i.quantity, i.out, i.available, format_money(i.rate_day, cur), format_money(i.deposit, cur),
                     t(i.condition) + ("" if i.active else f" ({t('désactivé')})"), format_money(i.repair_cost, cur), t("Révision due") if i.needs_service else ""]
            for c, v in enumerate(cells):
                self.park.setItem(r, c, _cell(v, c in (2, 3, 4, 5, 6, 8), i.id if c == 0 else None, "#b91c1c" if c == 9 else None))
        a = rs.alerts()
        parts = []
        if a["overdue"]:
            parts.append(f"<span style='color:#b91c1c'><b>{len(a['overdue'])}</b> {t('location(s) en retard')} : " + ", ".join(f"{s.client} ({s.days_late} j)" for s in a["overdue"][:5]) + "</span>")
        if a["today"]:
            parts.append(f"<b>{len(a['today'])}</b> {t('à rendre aujourd’hui')} : " + ", ".join(s.client for s in a["today"][:5]))
        self.banner.setText(" &nbsp;·&nbsp; ".join(parts) or t("Aucun retour en retard."))
