"""Factures proforma : liste, création / modification, impression PDF."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QTableWidget, QVBoxLayout, QWidget,
)

from app.i18n import t
from app.models.proforma import STATUSES
from app.printers.proforma_doc import build_proforma_pdf
from app.services import audit_service, permissions as perms, proforma_service as ps, settings_service
from app.ui.dialogs.chantier_dialog import _money
from app.ui.pages.rentals_page import _cell, _table
from app.ui.state import AppState
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.utils.helpers import format_money


def _qty() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(3)
    s.setRange(0, 1_000_000)
    return s


class ProformaDialog(QDialog):
    COLS = ("Désignation", "CDT", "Quantité", "Unité", "Prix unitaire", "Total")

    def __init__(self, parent=None, data: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("Facture proforma"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=760, min_height=640, preferred_width=880, preferred_height=760)
        self.client_id = data.get("client_id") if data else None
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.pick = QComboBox()
        self.pick.addItem(t("— Client saisi à la main —"), None)
        from sqlalchemy import select
        from app.database.connection import session_scope
        from app.models.client import Client
        with session_scope() as s:
            for cid, name in s.execute(select(Client.id, Client.name).order_by(Client.name)):
                self.pick.addItem(name, cid)
        self.pick.currentIndexChanged.connect(self._pick_client)
        form.addRow(t("Client existant"), self.pick)
        self.f = {}
        for key, label in (("client_name", "Client (Doit)"), ("client_phone", "Téléphone"), ("client_email", "Email"), ("client_ifu", "IFU"), ("client_rccm", "RCCM"),
                           ("client_regime", "Régime fiscal"), ("client_division", "Division fiscale"), ("client_address", "Adresse"), ("subject", "Objet")):
            self.f[key] = QLineEdit(data[key] if data else "")
            form.addRow(t(label), self.f[key])
        self.date = QDateEdit(QDate.currentDate() if not data else QDate(data["date"].year, data["date"].month, data["date"].day))
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        form.addRow(t("Date"), self.date)
        root.addLayout(form)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([t(c) for c in self.COLS])
        self.table.setColumnWidth(0, 260)
        root.addWidget(self.table, 1)
        self._rows: list = []
        row = QHBoxLayout()
        add = QPushButton(t("+ Ajouter une ligne"))
        add.clicked.connect(lambda: self._add_row())
        rm = QPushButton(t("Retirer la ligne"))
        rm.clicked.connect(self._remove_row)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch()
        root.addLayout(row)
        tax = QFormLayout()
        self.tax_label = QLineEdit(data["tax_label"] if data else "")
        self.tax_label.setPlaceholderText(t("ex. BIC (laisser vide si aucune taxe)"))
        self.tax_rate = _money()
        self.tax_rate.setDecimals(2)
        self.tax_rate.setValue(data["tax_rate"] if data else 0)
        tax.addRow(t("Taxe ajoutée au HT"), self.tax_label)
        tax.addRow(t("Taux (%)"), self.tax_rate)
        defaults = ps.defaults()
        self.responsible = QLineEdit(data["responsible"] if data else defaults["responsible"])
        self.responsible_phone = QLineEdit(data["responsible_phone"] if data else defaults["responsible_phone"])
        tax.addRow(t("Le Responsable"), self.responsible)
        tax.addRow(t("Téléphone du responsable"), self.responsible_phone)
        self.notes = QPlainTextEdit(data["notes"] if data else "")
        self.notes.setPlaceholderText(t("Conditions, validité, délai de livraison… (facultatif)"))
        self.notes.setMaximumHeight(60)
        tax.addRow(t("Notes"), self.notes)
        root.addLayout(tax)
        self.total_label = QLabel()
        self.total_label.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.total_label)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self.tax_rate.valueChanged.connect(self._totals)
        for l in (data["lines"] if data else [None]):
            self._add_row(l)
        if data and data.get("client_id"):
            i = self.pick.findData(data["client_id"])
            if i >= 0:
                self.pick.blockSignals(True)
                self.pick.setCurrentIndex(i)
                self.pick.blockSignals(False)

    def _add_row(self, line: dict | None = None) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        label, cdt, unit = QLineEdit(line["label"] if line else ""), QLineEdit(line["packaging"] if line else ""), QLineEdit(line["unit"] if line else "")
        qty, price, total = _qty(), _money(), QLabel("0")
        qty.setValue(line["quantity"] if line else 1)
        price.setValue(line["unit_price"] if line else 0)
        total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for c, w in enumerate((label, cdt, qty, unit, price, total)):
            self.table.setCellWidget(r, c, w)
        qty.valueChanged.connect(self._totals)
        price.valueChanged.connect(self._totals)
        self._rows.append((label, cdt, qty, unit, price, total))
        self._totals()

    def _remove_row(self) -> None:
        r = self.table.currentRow()
        if r >= 0 and len(self._rows) > 1:
            self.table.removeRow(r)
            self._rows.pop(r)
            self._totals()

    def _inputs(self):
        return [ps.LineInput(l.text(), q.value(), u.text(), p.value(), c.text()) for l, c, q, u, p, _t in self._rows]

    def _totals(self, *_a) -> None:
        for l, c, q, u, p, tot in self._rows:
            tot.setText(f"{q.value() * p.value():,.0f}".replace(",", " "))
        tt = ps.compute_totals([x for x in self._inputs()], self.tax_label.text() or "Taxe", self.tax_rate.value())
        cur = settings_service.get_shop_info().currency or "FCFA"
        extra = f" + {tt.tax_label} {format_money(tt.tax, cur)}" if tt.tax else ""
        self.total_label.setText(f"<b>{t('Total')} : {format_money(tt.total, cur)}</b> <span style='color:#64748b'>({t('HT')} {format_money(tt.subtotal, cur)}{extra})</span>")

    def _pick_client(self) -> None:
        cid = self.pick.currentData()
        self.client_id = cid
        if cid:
            for k, v in ps.client_defaults(cid).items():
                if k in self.f and v:
                    self.f[k].setText(v)

    def _accept(self) -> None:
        try:
            ps.compute_totals(self._inputs())
            if not self.f["client_name"].text().strip():
                raise ValueError(t("Indiquez le client."))
            if not any(l.label.strip() for l in self._inputs()):
                raise ValueError(t("Ajoutez au moins une ligne."))
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.accept()

    def values(self) -> tuple:
        d = self.date.date()
        fields = {k: w.text().strip() for k, w in self.f.items()}
        fields.update(client_id=self.client_id, tax_label=self.tax_label.text().strip(), tax_rate=self.tax_rate.value(),
                      responsible=self.responsible.text().strip(), responsible_phone=self.responsible_phone.text().strip(), notes=self.notes.toPlainText().strip())
        return self._inputs(), datetime(d.year(), d.month(), d.day(), datetime.now().hour, datetime.now().minute), fields


class ConvertDialog(QDialog):
    """Associe chaque ligne de la proforma à un produit du stock et choisit le mode de paiement."""

    def __init__(self, parent, proforma_id: int):
        super().__init__(parent)
        self.setWindowTitle(t("Transformer en vente"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=560, min_height=360, preferred_width=680, preferred_height=460)
        from sqlalchemy import select
        from app.database.connection import session_scope
        from app.models.product import Product
        d = ps.get(proforma_id)
        self.has_client = bool(d["client_id"])
        root = QVBoxLayout(self)
        root.addWidget(QLabel(t("Associez chaque ligne à un produit du stock. Le stock sera diminué et la vente enregistrée dans la caisse.")))
        with session_scope() as s:
            products = [(p.id, p.name) for p in s.scalars(select(Product).order_by(Product.name))]
        self.combos = []
        form = QFormLayout()
        for line, sug in zip(d["lines"], ps.suggest_products(proforma_id)):
            c = QComboBox()
            c.addItem(t("— choisir —"), None)
            for pid, name in products:
                c.addItem(name, pid)
            if sug:
                c.setCurrentIndex(c.findData(sug))
            form.addRow(f"{line['label']} ({line['quantity']:g} × {line['unit_price']:,.0f})".replace(",", " "), c)
            self.combos.append(c)
        root.addLayout(form)
        self.mode = QComboBox()
        self.mode.addItem(t("Payée en espèces"), False)
        self.mode.addItem(t("À crédit (dette du client)"), True)
        root.addWidget(self.mode)
        if d["totals"].tax > 0:
            note = QLabel(t("La taxe ajoutée sur la proforma n'est pas incluse dans la vente."))
            note.setStyleSheet("color: #b45309;")
            root.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def values(self):
        return [c.currentData() for c in self.combos], bool(self.mode.currentData())


class ProformasPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.can_manage = state.can(perms.MANAGE_PROFORMAS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(page_title(t("Factures proforma")))
        bar = QHBoxLayout()
        self.status = QComboBox()
        self.status.addItem(t("Toutes"), None)
        for s in STATUSES:
            self.status.addItem(t(s), s)
        self.status.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.status)
        bar.addStretch()
        layout.addLayout(bar)
        self.table = _table(["N°", "Date", "Client", "Objet", "Total", "Statut"])
        self.table.doubleClicked.connect(lambda *_: self._edit())
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.buttons = {}
        for key, label, slot, primary in (("new", "+ Nouvelle proforma", self._new, True), ("edit", "Modifier", self._edit, False),
                                          ("print", "Imprimer / PDF", self._print, True), ("dup", "Dupliquer", self._dup, False),
                                          ("sale", "Transformer en vente", self._convert, False), ("ok", "Marquer acceptée", lambda: self._status("Acceptée"), False),
                                          ("ko", "Marquer refusée", lambda: self._status("Refusée"), False), ("del", "Supprimer", self._delete, False)):
            b = QPushButton(t(label))
            if primary:
                b.setObjectName("Primary")
            if key == "del":
                b.setObjectName("Danger")
            b.clicked.connect(slot)
            if key != "print":
                b.setEnabled(self.can_manage)
            self.buttons[key] = b
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)
        self.refresh()

    def _id(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def _user(self):
        return self.state.user_id, getattr(self.state.current_user, "username", "")

    def _new(self) -> None:
        dlg = ProformaDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            lines, date, fields = dlg.values()
            pid = ps.save(lines, date=date, **fields)
            audit_service.log_action("Proforma créée", "Proforma", str(pid), *self._user())
            self.refresh()

    def _edit(self) -> None:
        pid = self._id()
        if not pid or not self.can_manage:
            return
        dlg = ProformaDialog(self, ps.get(pid))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            lines, date, fields = dlg.values()
            ps.save(lines, proforma_id=pid, date=date, **fields)
            self.refresh()

    def _print(self) -> None:
        pid = self._id()
        if not pid:
            warn(self, t("Sélectionnez une proforma."))
            return
        path = build_proforma_pdf(pid, Path(tempfile.gettempdir()) / f"proforma_{pid}.pdf")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _dup(self) -> None:
        pid = self._id()
        if pid:
            ps.duplicate(pid)
            self.refresh()

    def _convert(self) -> None:
        pid = self._id()
        if not pid:
            warn(self, t("Sélectionnez une proforma."))
            return
        dlg = ConvertDialog(self, pid)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ids, credit = dlg.values()
        try:
            sale_id = ps.convert_to_sale(pid, ids, on_credit=credit, user_id=self.state.user_id)
        except Exception as exc:  # noqa: BLE001 - stock insuffisant, prix minimum… : on explique, rien n'est enregistré
            warn(self, str(exc))
            return
        audit_service.log_action("Proforma transformée en vente", "Proforma", str(pid), *self._user())
        notify = getattr(self.state, "notify_data_changed", None)
        if notify:
            notify()
        self.refresh()
        info(self, t("Vente enregistrée. La proforma est marquée « Facturée »."))

    def _status(self, status: str) -> None:
        pid = self._id()
        if pid:
            ps.set_status(pid, status)
            self.refresh()

    def _delete(self) -> None:
        pid = self._id()
        if pid and confirm(self, t("Supprimer cette proforma ?")):
            ps.delete(pid)
            audit_service.log_action("Proforma supprimée", "Proforma", str(pid), *self._user())
            self.refresh()

    def refresh(self) -> None:
        cur = settings_service.get_shop_info().currency or "FCFA"
        rows = ps.list_all(self.status.currentData())
        self.table.setRowCount(len(rows))
        for r, x in enumerate(rows):
            for c, v in enumerate([x["number"], x["date"].strftime("%d/%m/%Y"), x["client"], x["subject"], format_money(x["total"], cur), t(x["status"])]):
                self.table.setItem(r, c, _cell(v, c == 4, x["id"] if c == 0 else None))
