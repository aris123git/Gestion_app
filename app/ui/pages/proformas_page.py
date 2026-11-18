"""Factures proforma : liste, création / modification, impression PDF."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QScrollArea,
    QComboBox, QCompleter, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QTableWidget, QVBoxLayout, QWidget,
)

from app.i18n import t
from app.models.proforma import STATUSES
from app.printers.proforma_doc import build_proforma_pdf, get_model, proforma_models, set_model
from app.services import audit_service, permissions as perms, proforma_service as ps, settings_service
from app.ui.dialogs.chantier_dialog import _money
from app.ui.pages.rentals_page import _cell, _table
from app.ui.widgets.batch import enable_multi, run_batch, selected_rows
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
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        root = QVBoxLayout(content)           # tout le formulaire défile : plus de lignes qui se chevauchent
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
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

        def field(key: str, label: str) -> QLineEdit:
            self.f[key] = QLineEdit(data[key] if data else "")
            return self.f[key]

        def pair(key_a: str, label_a: str, key_b: str, label_b: str) -> None:
            """Deux champs sur la même ligne pour garder tout le formulaire visible."""
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(field(key_a, label_a), 1)
            h.addWidget(QLabel(t(label_b)))
            h.addWidget(field(key_b, label_b), 1)
            form.addRow(t(label_a), box)

        form.addRow(t("Client (Doit)"), field("client_name", "Client (Doit)"))
        pair("client_phone", "Téléphone", "client_email", "Email")
        pair("client_ifu", "IFU", "client_rccm", "RCCM")
        pair("client_regime", "Régime fiscal", "client_division", "Division fiscale")
        form.addRow(t("Adresse"), field("client_address", "Adresse"))
        form.addRow(t("Objet"), field("subject", "Objet"))
        self.date = QDateEdit(QDate.currentDate() if not data else QDate(data["date"].year, data["date"].month, data["date"].day))
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        form.addRow(t("Date"), self.date)
        root.addLayout(form)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([t(c) for c in self.COLS])
        from PySide6.QtWidgets import QHeaderView
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 70), (2, 100), (3, 70), (4, 130), (5, 110)):
            head.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, width)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setMinimumHeight(320)
        root.addWidget(self.table, 1)
        self._rows: list = []
        self._catalog = {c["name"].strip().lower(): c for c in ps.catalog()}
        row = QHBoxLayout()
        add = QPushButton(t("+ Ajouter une ligne"))
        add.clicked.connect(lambda: self._add_row())
        rm = QPushButton(t("Retirer la ligne"))
        rm.clicked.connect(self._remove_row)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch()
        self.total_label = QLabel()
        self.total_label.setTextFormat(Qt.TextFormat.RichText)
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.total_label)
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
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)
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
        if self._catalog:
            comp = QCompleter(list(self._catalog), label)           # proposition des produits au fil de la frappe
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            label.setCompleter(comp)
            label.setPlaceholderText(t("Produit (tapez pour chercher) ou ligne libre"))

            applied = {"name": (line or {}).get("label", "").strip().lower()}   # produit dont le prix a déjà été proposé sur cette ligne

            def _filled(*_a, label=label, unit=unit, price=price, qty=qty, from_completer=False) -> None:
                prod = self._catalog.get(label.text().strip().lower())
                if not prod or applied["name"] == prod["name"].lower():
                    return                      # ligne libre, ou prix déjà proposé : on ne touche pas à ce que la personne a saisi
                applied["name"] = prod["name"].lower()
                label.setText(prod["name"])
                price.setValue(prod["price"])   # prix de vente par défaut, modifiable
                if not unit.text().strip():
                    unit.setText(prod["unit"])
                if from_completer:              # le curseur passe à la quantité seulement après un choix dans la liste
                    qty.setFocus()
                    qty.selectAll()

            comp.activated.connect(lambda *_a, f=_filled: f(from_completer=True))
            label.editingFinished.connect(_filled)
        self._rows.append((label, cdt, qty, unit, price, total))
        self._totals()
        self.table.scrollToBottom()
        self.table.setCurrentCell(r, 0)
        if line is None:
            label.setFocus()

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
        n = len([1 for x in self._inputs() if x.label.strip()])
        self.total_label.setText(f"<span style='font-size:15px'><b>{t('TOTAL')} ({n} {t('ligne(s)')}) : {format_money(tt.total, cur)}</b></span>" + (f" <span style='color:#64748b'>({t('HT')} {format_money(tt.subtotal, cur)}{extra})</span>" if tt.tax else ""))

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
        self._status_filter = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(page_title(t("Factures proforma")))
        top.addStretch()
        new = QPushButton(t("+ Nouvelle proforma"))
        new.setObjectName("Primary")
        new.setEnabled(self.can_manage)
        new.clicked.connect(self._new)
        top.addWidget(new)
        layout.addLayout(top)
        kp = QHBoxLayout()
        self.k_open, self.k_ok, self.k_ko = QLabel(), QLabel(), QLabel()
        for k in (self.k_open, self.k_ok, self.k_ko):
            k.setTextFormat(Qt.TextFormat.RichText)
            kp.addWidget(make_card(k), 1)
        layout.addLayout(kp)
        chips = QHBoxLayout()
        self._chips = {}
        for key, label in [(None, "Toutes")] + [(s, s) for s in STATUSES]:
            b = QPushButton(t(label))
            b.setCheckable(True)
            b.setStyleSheet("QPushButton:checked { background: #2563eb; color: #ffffff; border-color: #2563eb; }")
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self._chips[key] = b
            chips.addWidget(b)
        chips.addStretch()
        layout.addLayout(chips)
        body = QHBoxLayout()
        self.table = _table(["N°", "Date", "Client", "Objet", "Total", "Statut"])
        self.table.verticalHeader().setVisible(False)
        enable_multi(self.table)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda *_: self._edit())
        self.table.currentCellChanged.connect(lambda *_: self._show())
        body.addWidget(self.table, 3)
        side = QVBoxLayout()
        self.d_head = QLabel(t("Sélectionnez une proforma."))
        self.d_head.setTextFormat(Qt.TextFormat.RichText)
        self.d_head.setWordWrap(True)
        side.addWidget(self.d_head)
        self.d_lines = _table(["Désignation", "Qté", "Prix", "Total"])
        self.d_lines.verticalHeader().setVisible(False)
        self.d_lines.horizontalHeader().setStretchLastSection(True)
        side.addWidget(self.d_lines, 1)
        self.d_total = QLabel()
        self.d_total.setAlignment(Qt.AlignmentFlag.AlignRight)
        side.addWidget(self.d_total)
        side.addWidget(QLabel(t("Modèle d'impression")))
        self.model = QComboBox()
        for mid, label in proforma_models():
            self.model.addItem(label, mid)
        self.model.setCurrentIndex(max(0, self.model.findData(get_model())))
        self.model.currentIndexChanged.connect(lambda *_: set_model(self.model.currentData()))    # le choix est retenu
        side.addWidget(self.model)
        self.buttons = {}
        rows = [[("print", "Imprimer / PDF", self._print, True), ("send", "Envoyer", self._send, False), ("edit", "Modifier", self._edit, False)],
                [("sale", "Transformer en vente", self._convert, True), ("status", "Statut", None, False)],
                [("dup", "Dupliquer", self._dup, False), ("del", "Supprimer", self._delete, False)]]
        for spec in rows:
            row = QHBoxLayout()
            for key, label, slot, primary in spec:
                b = QPushButton(t(label))
                if primary:
                    b.setObjectName("Primary")
                if key == "del":
                    b.setObjectName("DangerOutline")
                if slot:
                    b.clicked.connect(slot)
                if key != "print":
                    b.setEnabled(self.can_manage)
                self.buttons[key] = b
                row.addWidget(b)
            side.addLayout(row)
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self.buttons["status"])
        for label, st in (("Marquer acceptée", "Acceptée"), ("Marquer refusée", "Refusée"), ("Remettre ouverte", STATUSES[0])):
            menu.addAction(t(label), lambda st=st: self._status(st))
        self.buttons["status"].setText(t("Statut"))
        self.buttons["status"].setMenu(menu)
        body.addLayout(side, 2)
        layout.addLayout(body, 1)
        self._chips[None].setChecked(True)
        self.refresh()

    def _set_filter(self, key) -> None:
        self._status_filter = key
        self.refresh()

    def _show(self) -> None:
        pid = self._id()
        has = bool(pid)
        for k, b in self.buttons.items():
            b.setEnabled(has and (k == "print" or self.can_manage))
        if not has:
            self.d_head.setText(t("Sélectionnez une proforma."))
            self.d_lines.setRowCount(0)
            self.d_total.setText("")
            return
        d = ps.get(pid)
        cur = settings_service.get_shop_info().currency or "FCFA"
        self.buttons["sale"].setEnabled(self.can_manage and d["status"] != "Facturée")
        self.d_head.setText(f"<b style='font-size:15px'>{d['number']} · {d['client_name']}</b><br>"
                            f"<span style='color:#64748b'>{d['subject'] or ''} · {t(d['status'])}</span>")
        self.d_lines.setRowCount(len(d["lines"]))
        for r, ln in enumerate(d["lines"]):
            vals = [ln["label"], f"{ln['quantity']:g} {ln['unit']}".strip(), format_money(ln["unit_price"], cur), format_money(ln["quantity"] * ln["unit_price"], cur)]
            for c, v in enumerate(vals):
                self.d_lines.setItem(r, c, _cell(v, c > 0))
        self.d_total.setText(f"<b>{t('Total')} {format_money(d['totals'].total, cur)}</b>")

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
        path = build_proforma_pdf(pid, Path(tempfile.gettempdir()) / f"proforma_{pid}.pdf", self.model.currentData())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _send(self) -> None:
        from app.ui.dialogs.send_document_dialog import SendDocumentDialog

        pid = self._id()
        if not pid:
            warn(self, t("Sélectionnez une proforma."))
            return
        d = ps.get(pid)
        path = build_proforma_pdf(pid, Path(tempfile.gettempdir()) / f"proforma_{pid}.pdf", self.model.currentData())
        shop = settings_service.get_shop_info().name or ""
        message = (f"Bonjour {d['client_name']}, \nVeuillez trouver ci-joint notre facture proforma N°{d['number']} "
                   f"d'un montant de {format_money(d['totals'].total)}.\nCordialement, {shop}").strip()
        SendDocumentDialog(self, path, d["client_phone"], d["client_email"], f"Facture proforma N°{d['number']}", message, "Envoyer la proforma").exec()

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
        rows = selected_rows(self.table)
        if len(rows) > 1:
            items = [(self.table.item(r, 0).data(Qt.ItemDataRole.UserRole), self.table.item(r, 0).text()) for r in rows]
            user = self._user()

            def one(pid: int) -> None:
                ps.delete(pid)
                audit_service.log_action("Proforma supprimée", "Proforma", str(pid), *user)

            if run_batch(self, t("Supprimer {n} proformas ?"), items, one, t("proforma(s) supprimée(s)")):
                self.refresh()
            return
        pid = self._id()
        if pid and confirm(self, t("Supprimer cette proforma ?")):
            ps.delete(pid)
            audit_service.log_action("Proforma supprimée", "Proforma", str(pid), *self._user())
            self.refresh()

    def refresh(self) -> None:
        cur = settings_service.get_shop_info().currency or "FCFA"
        keep = self._id()
        for k, b in self._chips.items():
            b.setChecked(k == self._status_filter)
        everything = ps.list_all()
        rows = [x for x in everything if self._status_filter in (None, x["status"])]
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, x in enumerate(rows):
            for c, v in enumerate([x["number"], x["date"].strftime("%d/%m/%Y"), x["client"], x["subject"], format_money(x["total"], cur), t(x["status"])]):
                self.table.setItem(r, c, _cell(v, c == 4, x["id"] if c == 0 else None))
        self.table.blockSignals(False)

        def kpi(label, status):
            sel = [x for x in everything if x["status"] in status]
            return (f"<span style='color:#64748b'>{label}</span><br><b style='font-size:22px'>{len(sel)} · "
                    f"{format_money(sum(x['total'] for x in sel), cur)}</b>")
        self.k_open.setText(kpi(t("Ouvertes (en attente)"), (STATUSES[0],)))
        self.k_ok.setText(kpi(t("Acceptées et facturées"), ("Acceptée", "Facturée")))
        self.k_ko.setText(kpi(t("Refusées"), ("Refusée",)))
        target = next((r for r in range(len(rows)) if rows[r]["id"] == keep), 0 if rows else -1)
        if target >= 0:
            self.table.selectRow(target)
        self._show()
