"""Fiche d'un chantier : résumé, dépenses, encaissements, avancement, avenants, devis/budget, échéancier."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QScrollArea, QCheckBox, QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)
from sqlalchemy import select

from app import config
from app.database.connection import session_scope
from app.i18n import t
from app.models.chantier import (
    EXPENSE_CATEGORIES, PAYMENT_KINDS, STATUS_ACCEPTED, STATUS_LABELS, STATUS_QUOTE, STATUS_REFUSED, STATUS_RUNNING,
    Chantier, ChantierAddendum, ChantierExpense, ChantierLot, ChantierMilestone, ChantierPayment,
)
from app.printers import chantier_docs as docs
from app.services import audit_service, chantier_service as cs, permissions as perms, settings_service
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, make_card, section_title, warn
from app.ui.widgets.money_spin import MoneySpinBox
from app.utils.helpers import format_money

PENDING = (STATUS_QUOTE, STATUS_ACCEPTED, STATUS_REFUSED)


def _table(headers: list[str], stretch: int = 1) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels([t(h) for h in headers])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setMinimumHeight(220)
    return table


def _scroll(widget: QWidget) -> QScrollArea:
    """Onglet défilant : les champs gardent leur taille normale, on fait défiler au lieu de les écraser."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(widget)
    return area


def _money() -> MoneySpinBox:
    box = MoneySpinBox()
    box.setRange(0, 10_000_000_000)
    box.setDecimals(0)
    box.setSingleStep(1000)
    return box


def _item(text, align_right: bool = False, data=None) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text))
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    return item


def _date_edit() -> QDateEdit:
    edit = QDateEdit(QDate.currentDate())
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd/MM/yyyy")
    return edit


def _to_dt(edit: QDateEdit) -> datetime:
    d = edit.date()
    return datetime(d.year(), d.month(), d.day(), datetime.now().hour, datetime.now().minute)


def open_file(relative: str) -> None:
    path = cs.attachment_path(relative)
    if path is None:
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class ChantierDialog(QDialog):
    def __init__(self, state, chantier_id: int, parent=None):
        super().__init__(parent)
        self.state, self.chantier_id = state, chantier_id
        self.currency = settings_service.get_shop_info().currency or "FCFA"
        self.can_manage = state.can(perms.MANAGE_CHANTIERS)
        self.can_add_expense = state.can(perms.ADD_CHANTIER_EXPENSES)
        self.can_finance = state.can(perms.VIEW_CHANTIER_FINANCE)
        self.user_id = state.user_id
        self.username = getattr(state.current_user, "username", "")
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=720, min_height=520, preferred_width=1040, preferred_height=720)
        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(self.title)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tab_summary = self._build_summary()
        self.tabs.addTab(_scroll(self.tab_summary), t("Résumé"))
        self.tab_expenses = self._build_expenses()
        self.tabs.addTab(_scroll(self.tab_expenses), t("Dépenses"))
        if self.can_finance:
            self.tab_payments = self._build_payments()
            self.tabs.addTab(_scroll(self.tab_payments), t("Encaissements"))
        self.tab_progress = self._build_progress()
        self.tabs.addTab(_scroll(self.tab_progress), t("Avancement"))
        if self.can_finance:
            self.tab_addenda = self._build_addenda()
            self.tabs.addTab(_scroll(self.tab_addenda), t("Avenants"))
            self.tab_quote = self._build_quote()
            self.tabs.addTab(_scroll(self.tab_quote), t("Devis / budget"))
            self.tab_schedule = self._build_schedule()
            self.tabs.addTab(_scroll(self.tab_schedule), t("Échéancier"))
        close = QPushButton(t("Fermer"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    # -- utilitaires -------------------------------------------------------------
    def _money_text(self, value: float) -> str:
        return format_money(value, self.currency)

    def _run(self, action, *args, **kwargs):
        """Exécute une action du service ; affiche l'erreur lisible. Retourne (ok, valeur)."""
        try:
            return True, action(*args, **kwargs)
        except ValueError as exc:
            warn(self, str(exc))
            return False, None

    def _log(self, action: str, details: str) -> None:
        audit_service.log_action(action, "Chantier", details, self.user_id, self.username)

    def _pick_file(self, label: QLabel) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("Joindre un reçu, une facture ou une photo"), "", t("Images et documents (*.png *.jpg *.jpeg *.pdf *.webp *.doc *.docx *.xls *.xlsx);;Tous les fichiers (*)"))
        if path:
            label.setText(path)
            label.setToolTip(path)

    def _attach_row(self):
        label = QLabel(t("Aucun fichier"))
        label.setStyleSheet("color: #64748b;")
        button = QPushButton(t("📎 Joindre un fichier"))
        button.clicked.connect(lambda: self._pick_file(label))
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(button)
        h.addWidget(label, 1)
        return box, label

    @staticmethod
    def _attachment_of(label: QLabel) -> str | None:
        return label.toolTip() or None

    # -- données ---------------------------------------------------------------------
    def _chantier(self) -> dict:
        with session_scope() as session:
            c = session.get(Chantier, self.chantier_id)
            return {"number": c.number, "name": c.name, "status": c.status, "client": c.client_label, "location": c.location,
                    "amount": float(c.amount or 0), "mode": c.progress_mode, "progress": float(c.progress_pct or 0), "retention": float(c.retention_pct or 0)}

    def refresh(self) -> None:
        self.data = self._chantier()
        s = cs.summary(self.chantier_id)
        self.summary = s
        self.title.setText(f"{self.data['number']} — {self.data['name']}   [{t(STATUS_LABELS.get(self.data['status'], ''))}]")
        self._refresh_summary(s)
        self._refresh_expenses()
        pending = self.data["status"] in PENDING
        for widget in (self.exp_form_box,):
            widget.setEnabled(not pending and (self.can_add_expense))
        if self.can_finance:
            self._refresh_payments()
            self._refresh_addenda()
            self._refresh_quote()
            self._refresh_schedule()
            self.pay_form_box.setEnabled(not pending and self.can_manage)
            self.add_form_box.setEnabled(self.can_manage)
        self._refresh_progress()

    # -- Résumé ----------------------------------------------------------------------------
    def _build_summary(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.kpi = QLabel()
        self.kpi.setTextFormat(Qt.TextFormat.RichText)
        self.kpi.setWordWrap(True)
        v.addWidget(make_card(self.kpi))
        self.alerts = QLabel()
        self.alerts.setWordWrap(True)
        self.alerts.setStyleSheet("color: #b91c1c; font-weight: 600;")
        v.addWidget(self.alerts)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        v.addWidget(QLabel(t("Avancement du chantier")))
        v.addWidget(self.bar)
        row = QHBoxLayout()
        self.status_combo = QComboBox()
        self.btn_status = QPushButton(t("Changer le statut"))
        self.btn_status.clicked.connect(self._change_status)
        self.btn_convert = QPushButton(t("✅ Convertir le devis en marché"))
        self.btn_convert.setObjectName("Primary")
        self.btn_convert.clicked.connect(self._convert)
        row.addWidget(self.status_combo)
        row.addWidget(self.btn_status)
        row.addWidget(self.btn_convert)
        self.btn_edit = QPushButton(t("✏️ Modifier client / informations"))
        self.btn_edit.clicked.connect(self._edit_info)
        self.btn_edit.setEnabled(self.can_manage)
        row.addWidget(self.btn_edit)
        row.addStretch()
        v.addLayout(row)
        docs_row = QHBoxLayout()
        for label, fn in ((t("🖨 Devis / marché (PDF)"), self._pdf_quote), (t("🧾 Facture du client (PDF)"), self._pdf_invoice), (t("🖨 Rapport de chantier (PDF)"), self._pdf_report)):
            button = QPushButton(label)
            button.clicked.connect(fn)
            docs_row.addWidget(button)
            if not self.can_finance:
                button.setEnabled(False)
        docs_row.addStretch()
        v.addLayout(docs_row)
        v.addStretch()
        if not self.can_manage:
            for b in (self.status_combo, self.btn_status, self.btn_convert):
                b.setEnabled(False)
        return w

    def _refresh_summary(self, s) -> None:
        d = self.data
        lines = [f"<b>{t('Client')}</b> : {d['client'] or '—'} &nbsp;·&nbsp; <b>{t('Lieu')}</b> : {d['location'] or '—'}"]
        if self.can_finance:
            lines += [
                f"<b>{t('Montant du marché')}</b> : {self._money_text(s.contract)}" + (f" ({t('dont avenants')} {self._money_text(s.addenda_total)})" if s.addenda_total else ""),
                f"<b>{t('Encaissé')}</b> : {self._money_text(s.received)} &nbsp;·&nbsp; <b>{t('Reste à encaisser')}</b> : <span style='color:#1d4ed8'>{self._money_text(s.remaining_to_receive)}</span>",
                f"<b>{t('Dépensé')}</b> : {self._money_text(s.spent)} ({s.spent_pct:g} %) &nbsp;·&nbsp; <b>{t('Dettes fournisseurs')}</b> : {self._money_text(s.supplier_debt)}",
                f"<b>{t('Marge')}</b> : <span style='color:{'#15803d' if s.margin >= 0 else '#b91c1c'}'>{self._money_text(s.margin)} ({s.margin_pct:g} %)</span> &nbsp;·&nbsp; <b>{t('Trésorerie')}</b> : {self._money_text(s.cash)}",
            ]
        else:
            lines.append(f"<b>{t('Dépensé')}</b> : {self._money_text(s.spent)}")
        if s.by_category:
            lines.append("<br/>" + " &nbsp;|&nbsp; ".join(f"{t(k)} : {self._money_text(v)}" for k, v in sorted(s.by_category.items())))
        self.kpi.setText("<br/>".join(lines))
        self.alerts.setText("\n".join("⚠ " + a for a in s.alerts) if self.can_finance else "")
        self.bar.setValue(int(round(s.progress_pct)))
        self.bar.setFormat(f"{s.progress_pct:g} %")
        self.status_combo.clear()
        for key, label in STATUS_LABELS.items():
            if key != self.data["status"] and key in cs._TRANSITIONS.get(self.data["status"], set()):
                self.status_combo.addItem(t(label), key)
        self.btn_status.setEnabled(self.can_manage and self.status_combo.count() > 0)
        self.btn_convert.setVisible(self.data["status"] in (STATUS_QUOTE, STATUS_ACCEPTED))

    def _change_status(self) -> None:
        status = self.status_combo.currentData()
        ok, _ = self._run(cs.set_status, self.chantier_id, status)
        if ok:
            self._log("Statut chantier", f"{self.data['number']} → {status}")
            self.refresh()
            self.state.data_changed.emit()

    def _convert(self) -> None:
        if confirm(self, t("Convertir ce devis en marché ? Le montant devient le prix du marché et les lignes le budget prévisionnel.")):
            ok, _ = self._run(cs.convert_to_market, self.chantier_id)
            if ok:
                self._log("Devis converti en marché", self.data["number"])
                self.refresh()
                self.state.data_changed.emit()

    def _open_pdf(self, path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _pdf_quote(self) -> None:
        self._open_pdf(docs.build_quote(self.chantier_id))

    def _pdf_invoice(self) -> None:
        self._open_pdf(docs.build_invoice(self.chantier_id))

    def _edit_info(self) -> None:
        from app.ui.pages.chantiers_page import NewChantierDialog
        dlg = NewChantierDialog(self, self.data['status'] in PENDING)
        dlg.setWindowTitle(t("Modifier le chantier"))
        with session_scope() as session:
            c = session.get(Chantier, self.chantier_id)
            dlg.name.setText(c.name)
            dlg.client.setCurrentText(c.client_label or '')
            if c.client_id is not None and dlg.client.findData(c.client_id) >= 0:
                dlg.client.setCurrentIndex(dlg.client.findData(c.client_id))
            dlg.location.setText(c.location or '')
            dlg.amount.setValue(float(c.amount or 0))
            dlg.retention.setValue(float(c.retention_pct or 0))
            dlg.notes.setPlainText(c.notes or '')
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        ok, _ = self._run(cs.update, self.chantier_id, name=v['name'], client_id=v['client_id'], client_label=v['client_label'], location=v['location'],
                          start_date=v['start_date'], end_planned=v['end_planned'], amount=v['amount'], notes=v['notes'], retention_pct=v['retention_pct'])
        if ok:
            self._log('Chantier modifié', self.data['number'])
            self.refresh()
            self.state.data_changed.emit()

    def _pdf_report(self) -> None:
        self._open_pdf(docs.build_report(self.chantier_id))

    # -- Dépenses ------------------------------------------------------------------------------
    def _build_expenses(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.exp_form_box = QWidget()
        form = QFormLayout(self.exp_form_box)
        self.exp_category = QComboBox()
        self.exp_category.addItems(EXPENSE_CATEGORIES)
        self.exp_label = QLineEdit()
        self.exp_label.setPlaceholderText(t("Nom de la dépense (ex. 20 sacs de ciment)"))
        self.exp_supplier = QLineEdit()
        self.exp_supplier.setPlaceholderText(t("Fournisseur"))
        self.exp_date = _date_edit()
        self.exp_amount = _money()
        self.exp_credit = QCheckBox(t("À crédit (dette fournisseur)"))
        self.exp_paid = _money()
        self.exp_paid.setEnabled(False)
        self.exp_credit.toggled.connect(self.exp_paid.setEnabled)
        self.exp_worker = QLineEdit()
        self.exp_worker.setPlaceholderText(t("Main-d'œuvre : nom de l'ouvrier"))
        self.exp_days = QDoubleSpinBox()
        self.exp_days.setRange(0, 10000)
        self.exp_days.setDecimals(1)
        self.exp_rate = _money()
        attach_box, self.exp_file = self._attach_row()
        form.addRow(t("Catégorie"), self.exp_category)
        form.addRow(t("Nom"), self.exp_label)
        form.addRow(t("Fournisseur"), self.exp_supplier)
        form.addRow(t("Date"), self.exp_date)
        form.addRow(t("Montant"), self.exp_amount)
        form.addRow("", self.exp_credit)
        form.addRow(t("Déjà payé"), self.exp_paid)
        form.addRow(t("Ouvrier"), self.exp_worker)
        form.addRow(t("Jours × tarif/jour"), self._pair(self.exp_days, self.exp_rate))
        form.addRow(t("Pièce jointe"), attach_box)
        add = QPushButton(t("Enregistrer la dépense"))
        add.setObjectName("Primary")
        add.clicked.connect(self._add_expense)
        form.addRow("", add)
        v.addWidget(make_card(self.exp_form_box))
        self.exp_table = _table(["Date", "Catégorie", "Nom", "Fournisseur / ouvrier", "Montant", "Payé", "Reste dû", "Pièce"], stretch=2)
        v.addWidget(self.exp_table, 1)
        row = QHBoxLayout()
        self.btn_open_exp = QPushButton(t("📎 Ouvrir la pièce"))
        self.btn_open_exp.clicked.connect(self._open_expense_file)
        self.btn_pay_exp = QPushButton(t("Régler une dette"))
        self.btn_pay_exp.clicked.connect(self._pay_expense)
        self.btn_del_exp = QPushButton(t("Supprimer"))
        self.btn_del_exp.setObjectName("Danger")
        self.btn_del_exp.clicked.connect(self._delete_expense)
        for b in (self.btn_open_exp, self.btn_pay_exp, self.btn_del_exp):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.btn_pay_exp.setEnabled(self.can_manage)
        self.btn_del_exp.setEnabled(self.can_manage)
        return w

    @staticmethod
    def _pair(a, b) -> QWidget:
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(a)
        h.addWidget(QLabel("×"))
        h.addWidget(b)
        return box

    def _add_expense(self) -> None:
        paid = self.exp_paid.value() if self.exp_credit.isChecked() else None
        ok, _ = self._run(cs.add_expense, self.chantier_id, category=self.exp_category.currentText(), label=self.exp_label.text(),
                          amount=self.exp_amount.value(), amount_paid=paid, supplier=self.exp_supplier.text(), date=_to_dt(self.exp_date),
                          worker=self.exp_worker.text(), days=self.exp_days.value(), daily_rate=self.exp_rate.value(),
                          attachment_source=self._attachment_of(self.exp_file), user_id=self.user_id)
        if not ok:
            return
        self._log("Dépense chantier", f"{self.data['number']} {self.exp_category.currentText()} {self.exp_label.text()}")
        for edit in (self.exp_label, self.exp_supplier, self.exp_worker):
            edit.clear()
        for spin in (self.exp_amount, self.exp_paid, self.exp_days, self.exp_rate):
            spin.setValue(0)
        self.exp_credit.setChecked(False)
        self.exp_file.setText(t("Aucun fichier"))
        self.exp_file.setToolTip("")
        self.refresh()
        self.state.data_changed.emit()

    def _refresh_expenses(self) -> None:
        with session_scope() as session:
            rows = session.scalars(select(ChantierExpense).where(ChantierExpense.chantier_id == self.chantier_id).order_by(ChantierExpense.date.desc(), ChantierExpense.id.desc())).all()
            data = [(e.id, e.date, e.category, e.label, e.supplier or e.worker, float(e.amount), float(e.amount_paid), e.attachment) for e in rows]
        self.exp_table.setRowCount(len(data))
        for r, (eid, date, cat, label, who, amount, paid, att) in enumerate(data):
            for c, (text, right) in enumerate(((f"{date:%d/%m/%Y}", False), (t(cat), False), (label, False), (who, False), (self._money_text(amount), True),
                                                (self._money_text(paid), True), (self._money_text(amount - paid), True), ("📎" if att else "", False))):
                self.exp_table.setItem(r, c, _item(text, right, (eid, att) if c == 0 else None))

    def _selected_expense(self):
        row = self.exp_table.currentRow()
        return self.exp_table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def _open_expense_file(self) -> None:
        sel = self._selected_expense()
        if sel and sel[1]:
            open_file(sel[1])

    def _pay_expense(self) -> None:
        sel = self._selected_expense()
        if not sel:
            return
        amount, ok = QInputDialog.getDouble(self, t("Régler une dette"), t("Montant payé au fournisseur :"), 0, 0, 10_000_000_000, 0)
        if ok and amount > 0:
            done, _ = self._run(cs.pay_expense, sel[0], amount)
            if done:
                self._log("Dette chantier réglée", f"{self.data['number']} {amount:g}")
                self.refresh()

    def _delete_expense(self) -> None:
        sel = self._selected_expense()
        if sel and confirm(self, t("Supprimer cette dépense ?")):
            cs.delete_expense(sel[0])
            self._log("Dépense chantier supprimée", f"{self.data['number']} #{sel[0]}")
            self.refresh()
            self.state.data_changed.emit()

    # -- Encaissements -------------------------------------------------------------------------------
    def _build_payments(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.pay_form_box = QWidget()
        form = QFormLayout(self.pay_form_box)
        self.pay_kind = QComboBox()
        self.pay_kind.addItems(PAYMENT_KINDS)
        self.pay_amount = _money()
        self.pay_method = QComboBox()
        self.pay_method.addItems(["Espèces", "Mobile Money", "Virement", "Chèque"])
        self.pay_ref = QLineEdit()
        self.pay_ref.setPlaceholderText(t("N° de chèque, référence Mobile Money…"))
        self.pay_date = _date_edit()
        attach_box, self.pay_file = self._attach_row()
        form.addRow(t("Nature"), self.pay_kind)
        form.addRow(t("Montant reçu"), self.pay_amount)
        form.addRow(t("Mode de paiement"), self.pay_method)
        form.addRow(t("Référence"), self.pay_ref)
        form.addRow(t("Date"), self.pay_date)
        form.addRow(t("Pièce jointe"), attach_box)
        add = QPushButton(t("Enregistrer l'encaissement"))
        add.setObjectName("Primary")
        add.clicked.connect(self._add_payment)
        form.addRow("", add)
        v.addWidget(make_card(self.pay_form_box))
        self.pay_table = _table(["N°", "Date", "Nature", "Mode", "Référence", "Montant"], stretch=4)
        v.addWidget(self.pay_table, 1)
        row = QHBoxLayout()
        receipt = QPushButton(t("🖨 Reçu (PDF)"))
        receipt.clicked.connect(self._receipt)
        open_file_btn = QPushButton(t("📎 Ouvrir la pièce"))
        open_file_btn.clicked.connect(self._open_payment_file)
        self.btn_del_pay = QPushButton(t("Supprimer"))
        self.btn_del_pay.setObjectName("Danger")
        self.btn_del_pay.clicked.connect(self._delete_payment)
        self.btn_del_pay.setEnabled(self.can_manage)
        for b in (receipt, open_file_btn, self.btn_del_pay):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        return w

    def _add_payment(self) -> None:
        ok, pid = self._run(cs.add_payment, self.chantier_id, amount=self.pay_amount.value(), kind=self.pay_kind.currentText(), method=self.pay_method.currentText(),
                            reference=self.pay_ref.text(), date=_to_dt(self.pay_date), attachment_source=self._attachment_of(self.pay_file), user_id=self.user_id)
        if not ok:
            return
        self._log("Encaissement chantier", f"{self.data['number']} {self.pay_kind.currentText()} {self.pay_amount.value():g}")
        self.pay_amount.setValue(0)
        self.pay_ref.clear()
        self.pay_file.setText(t("Aucun fichier"))
        self.pay_file.setToolTip("")
        self.refresh()
        self.state.data_changed.emit()
        if confirm(self, t("Encaissement enregistré. Imprimer le reçu ?")):
            self._open_pdf(docs.build_receipt(pid))

    def _refresh_payments(self) -> None:
        with session_scope() as session:
            rows = session.scalars(select(ChantierPayment).where(ChantierPayment.chantier_id == self.chantier_id).order_by(ChantierPayment.date.desc(), ChantierPayment.id.desc())).all()
            data = [(p.id, p.number, p.date, p.kind, p.method, p.reference, float(p.amount), p.attachment) for p in rows]
        self.pay_table.setRowCount(len(data))
        for r, (pid, number, date, kind, method, ref, amount, att) in enumerate(data):
            for c, (text, right) in enumerate(((number, False), (f"{date:%d/%m/%Y}", False), (t(kind), False), (t(method), False), (ref, False), (self._money_text(amount), True))):
                self.pay_table.setItem(r, c, _item(text, right, (pid, att) if c == 0 else None))

    def _selected_payment(self):
        row = self.pay_table.currentRow()
        return self.pay_table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def _receipt(self) -> None:
        sel = self._selected_payment()
        if sel:
            self._open_pdf(docs.build_receipt(sel[0]))

    def _open_payment_file(self) -> None:
        sel = self._selected_payment()
        if sel and sel[1]:
            open_file(sel[1])

    def _delete_payment(self) -> None:
        sel = self._selected_payment()
        if sel and confirm(self, t("Supprimer cet encaissement ?")):
            cs.delete_payment(sel[0])
            self._log("Encaissement chantier supprimé", f"{self.data['number']} #{sel[0]}")
            self.refresh()
            self.state.data_changed.emit()

    # -- Avancement ----------------------------------------------------------------------------------------
    def _build_progress(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel(t("Deux façons de suivre l'avancement : saisir un pourcentage à chaque visite, ou découper le marché en lots avec un poids (fondation 20 %, murs 30 %…) et cocher les lots terminés."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b;")
        v.addWidget(hint)
        manual = QHBoxLayout()
        manual.addWidget(QLabel(t("Avancement saisi (%) :")))
        self.prog_spin = QDoubleSpinBox()
        self.prog_spin.setRange(0, 100)
        self.prog_spin.setDecimals(1)
        self.prog_spin.setSuffix(" %")
        save = QPushButton(t("Enregistrer l'avancement"))
        save.clicked.connect(self._save_progress)
        manual.addWidget(self.prog_spin)
        manual.addWidget(save)
        manual.addStretch()
        v.addLayout(manual)
        v.addWidget(section_title(t("Lots de travaux")))
        lot_form = QHBoxLayout()
        self.lot_label = QLineEdit()
        self.lot_label.setPlaceholderText(t("Nom du lot (ex. Fondations)"))
        self.lot_weight = QDoubleSpinBox()
        self.lot_weight.setRange(0, 100)
        self.lot_weight.setSuffix(" %")
        add = QPushButton(t("Ajouter le lot"))
        add.clicked.connect(self._add_lot)
        lot_form.addWidget(self.lot_label, 2)
        lot_form.addWidget(self.lot_weight)
        lot_form.addWidget(add)
        v.addLayout(lot_form)
        self.lot_table = _table(["Terminé", "Lot", "Poids"], stretch=1)
        self.lot_table.itemChanged.connect(self._lot_toggled)
        v.addWidget(self.lot_table, 1)
        row = QHBoxLayout()
        self.use_lots = QPushButton(t("Calculer l'avancement avec les lots"))
        self.use_lots.clicked.connect(self._use_lots)
        del_lot = QPushButton(t("Supprimer le lot"))
        del_lot.setObjectName("Danger")
        del_lot.clicked.connect(self._delete_lot)
        row.addWidget(self.use_lots)
        row.addWidget(del_lot)
        row.addStretch()
        v.addLayout(row)
        self._loading_lots = False
        return w

    def _refresh_progress(self) -> None:
        self.prog_spin.setValue(self.data["progress"])
        with session_scope() as session:
            rows = session.scalars(select(ChantierLot).where(ChantierLot.chantier_id == self.chantier_id).order_by(ChantierLot.id)).all()
            data = [(l.id, l.label, float(l.weight), l.done) for l in rows]
        self._loading_lots = True
        self.lot_table.setRowCount(len(data))
        for r, (lid, label, weight, done) in enumerate(data):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, lid)
            self.lot_table.setItem(r, 0, check)
            self.lot_table.setItem(r, 1, _item(label))
            self.lot_table.setItem(r, 2, _item(f"{weight:g} %", True))
        self._loading_lots = False
        self.use_lots.setText(t("✔ L'avancement est calculé avec les lots") if self.data["mode"] == "lots" else t("Calculer l'avancement avec les lots"))

    def _save_progress(self) -> None:
        ok, _ = self._run(cs.set_progress, self.chantier_id, self.prog_spin.value())
        if ok:
            self._log("Avancement chantier", f"{self.data['number']} {self.prog_spin.value():g} %")
            self.refresh()
            self.state.data_changed.emit()

    def _add_lot(self) -> None:
        ok, _ = self._run(cs.add_lot, self.chantier_id, self.lot_label.text(), self.lot_weight.value())
        if ok:
            self.lot_label.clear()
            self.lot_weight.setValue(0)
            self.refresh()

    def _lot_toggled(self, item: QTableWidgetItem) -> None:
        if self._loading_lots or item.column() != 0:
            return
        cs.set_lot_done(item.data(Qt.ItemDataRole.UserRole), item.checkState() == Qt.CheckState.Checked)
        self.refresh()
        self.state.data_changed.emit()

    def _use_lots(self) -> None:
        cs.update(self.chantier_id, progress_mode="lots")
        self.refresh()

    def _delete_lot(self) -> None:
        row = self.lot_table.currentRow()
        if row >= 0 and confirm(self, t("Supprimer ce lot ?")):
            cs.delete_lot(self.lot_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            self.refresh()

    # -- Avenants ----------------------------------------------------------------------------------------------
    def _build_addenda(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.add_form_box = QWidget()
        form = QFormLayout(self.add_form_box)
        self.add_label = QLineEdit()
        self.add_label.setPlaceholderText(t("Travaux supplémentaires demandés par le client"))
        self.add_amount = QDoubleSpinBox()
        self.add_amount.setRange(-10_000_000_000, 10_000_000_000)
        self.add_amount.setDecimals(0)
        self.add_amount.setToolTip(t("Négatif pour une moins-value"))
        self.add_date = _date_edit()
        attach_box, self.add_file = self._attach_row()
        form.addRow(t("Objet de l'avenant"), self.add_label)
        form.addRow(t("Montant (+ ou −)"), self.add_amount)
        form.addRow(t("Date"), self.add_date)
        form.addRow(t("Trace écrite (avenant signé)"), attach_box)
        add = QPushButton(t("Enregistrer l'avenant"))
        add.setObjectName("Primary")
        add.clicked.connect(self._add_addendum)
        form.addRow("", add)
        v.addWidget(make_card(self.add_form_box))
        self.add_table = _table(["N°", "Date", "Objet", "Montant", "Pièce"], stretch=2)
        v.addWidget(self.add_table, 1)
        row = QHBoxLayout()
        open_btn = QPushButton(t("📎 Ouvrir la pièce"))
        open_btn.clicked.connect(self._open_addendum_file)
        row.addWidget(open_btn)
        row.addStretch()
        v.addLayout(row)
        return w

    def _add_addendum(self) -> None:
        ok, _ = self._run(cs.add_addendum, self.chantier_id, label=self.add_label.text(), amount=self.add_amount.value(), date=_to_dt(self.add_date),
                          attachment_source=self._attachment_of(self.add_file), user_id=self.user_id)
        if ok:
            self._log("Avenant chantier", f"{self.data['number']} {self.add_label.text()} {self.add_amount.value():g}")
            self.add_label.clear()
            self.add_amount.setValue(0)
            self.add_file.setText(t("Aucun fichier"))
            self.add_file.setToolTip("")
            self.refresh()
            self.state.data_changed.emit()

    def _refresh_addenda(self) -> None:
        with session_scope() as session:
            rows = session.scalars(select(ChantierAddendum).where(ChantierAddendum.chantier_id == self.chantier_id).order_by(ChantierAddendum.number)).all()
            data = [(a.id, a.number, a.date, a.label, float(a.amount), a.attachment) for a in rows]
        self.add_table.setRowCount(len(data))
        for r, (aid, number, date, label, amount, att) in enumerate(data):
            for c, (text, right) in enumerate(((number, False), (f"{date:%d/%m/%Y}", False), (label, False), (self._money_text(amount), True), ("📎" if att else "", False))):
                self.add_table.setItem(r, c, _item(text, right, att if c == 0 else None))

    def _open_addendum_file(self) -> None:
        row = self.add_table.currentRow()
        if row >= 0:
            att = self.add_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if att:
                open_file(att)

    # -- Devis / budget -----------------------------------------------------------------------------------------
    def _build_quote(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel(t("Lignes du devis : elles servent de budget prévisionnel une fois le devis converti en marché. Double-cliquez une cellule pour la modifier."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b;")
        v.addWidget(hint)
        self.quote_table = QTableWidget(0, 5)
        self.quote_table.setHorizontalHeaderLabels([t(h) for h in ("Désignation", "Quantité", "Unité", "Prix unitaire", "Catégorie")])
        self.quote_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.quote_table, 1)
        self.quote_total = QLabel()
        v.addWidget(self.quote_total)
        row = QHBoxLayout()
        add = QPushButton(t("+ Ajouter une ligne"))
        add.clicked.connect(lambda: self._quote_row(("", 1, "", 0, "Matériel")))
        save = QPushButton(t("Enregistrer les lignes"))
        save.setObjectName("Primary")
        save.clicked.connect(self._save_quote)
        del_btn = QPushButton(t("Supprimer la ligne"))
        del_btn.clicked.connect(lambda: self.quote_table.removeRow(self.quote_table.currentRow()) if self.quote_table.currentRow() >= 0 else None)
        set_amount = QPushButton(t("Prendre le total comme montant du marché"))
        set_amount.clicked.connect(self._amount_from_lines)
        for b in (add, del_btn, save, set_amount):
            row.addWidget(b)
            b.setEnabled(self.can_manage)
        row.addStretch()
        v.addLayout(row)
        return w

    def _quote_row(self, values) -> None:
        r = self.quote_table.rowCount()
        self.quote_table.insertRow(r)
        for c, value in enumerate(values):
            self.quote_table.setItem(r, c, QTableWidgetItem(f"{value:g}" if isinstance(value, (int, float)) else str(value)))

    def _refresh_quote(self) -> None:
        from app.models.chantier import ChantierLine
        with session_scope() as session:
            rows = session.scalars(select(ChantierLine).where(ChantierLine.chantier_id == self.chantier_id).order_by(ChantierLine.id)).all()
            data = [(l.label, float(l.quantity), l.unit, float(l.unit_price), l.category) for l in rows]
        self.quote_table.setRowCount(0)
        for values in data:
            self._quote_row(values)
        total = sum(q * p for _l, q, _u, p, _c in data)
        self.quote_total.setText(f"<b>{t('Total des lignes')}</b> : {self._money_text(total)} &nbsp;·&nbsp; <b>{t('Montant du marché')}</b> : {self._money_text(self.data['amount'])}")

    def _quote_lines(self) -> list:
        from app.utils.helpers import to_float
        lines = []
        for r in range(self.quote_table.rowCount()):
            cell = lambda c: (self.quote_table.item(r, c).text() if self.quote_table.item(r, c) else "")  # noqa: E731
            lines.append(cs.LineInput(cell(0), to_float(cell(1), 1.0), cell(2), to_float(cell(3)), cell(4) or "Matériel"))
        return lines

    def _save_quote(self) -> None:
        ok, _ = self._run(cs.replace_lines, self.chantier_id, self._quote_lines())
        if ok:
            self.refresh()

    def _amount_from_lines(self) -> None:
        total = sum(l.quantity * l.unit_price for l in self._quote_lines())
        if total > 0:
            cs.replace_lines(self.chantier_id, self._quote_lines())
            cs.update(self.chantier_id, amount=total)
            self.refresh()
            self.state.data_changed.emit()

    # -- Échéancier ---------------------------------------------------------------------------------------------------
    def _build_schedule(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        form = QHBoxLayout()
        self.ms_label = QLineEdit()
        self.ms_label.setPlaceholderText(t("Échéance (ex. À la signature)"))
        self.ms_pct = QDoubleSpinBox()
        self.ms_pct.setRange(0, 100)
        self.ms_pct.setSuffix(" %")
        self.ms_date = _date_edit()
        add = QPushButton(t("Ajouter"))
        add.clicked.connect(self._add_milestone)
        add.setEnabled(self.can_manage)
        for widget, stretch in ((self.ms_label, 2), (self.ms_pct, 0), (self.ms_date, 0), (add, 0)):
            form.addWidget(widget, stretch)
        v.addLayout(form)
        self.ms_table = _table(["Échéance", "Date prévue", "%", "Prévu", "Cumul prévu", "Situation"], stretch=0)
        v.addWidget(self.ms_table, 1)
        row = QHBoxLayout()
        delete = QPushButton(t("Supprimer"))
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete_milestone)
        delete.setEnabled(self.can_manage)
        row.addWidget(delete)
        row.addStretch()
        v.addLayout(row)
        return w

    def _add_milestone(self) -> None:
        ok, _ = self._run(cs.add_milestone, self.chantier_id, self.ms_label.text(), self.ms_pct.value(), _to_dt(self.ms_date))
        if ok:
            self.ms_label.clear()
            self.ms_pct.setValue(0)
            self.refresh()

    def _refresh_schedule(self) -> None:
        with session_scope() as session:
            rows = session.scalars(select(ChantierMilestone).where(ChantierMilestone.chantier_id == self.chantier_id)).all()
            ids = {m.label: (m.id, float(m.pct)) for m in rows}
        s = self.summary
        self.ms_table.setRowCount(len(s.planned_vs_received))
        for r, (label, planned, cumulative, due) in enumerate(s.planned_vs_received):
            mid, pct = ids.get(label, (None, 0.0))
            state = t("Reçu") if s.received + cs.EPS >= cumulative else (t("En retard") if due and due < datetime.now() else t("À venir"))
            for c, (text, right) in enumerate(((label, False), (f"{due:%d/%m/%Y}" if due else "", False), (f"{pct:g} %", True), (self._money_text(planned), True), (self._money_text(cumulative), True), (state, False))):
                self.ms_table.setItem(r, c, _item(text, right, mid if c == 0 else None))

    def _delete_milestone(self) -> None:
        row = self.ms_table.currentRow()
        if row >= 0:
            cs.delete_milestone(self.ms_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            self.refresh()
