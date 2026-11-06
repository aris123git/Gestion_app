"""Chantiers / marchés (type Entreprise) : liste, résultat global, nouveau devis ou marché, fiche du chantier."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.controllers.client_controller import ClientController
from app.i18n import t
from app.models.chantier import STATUS_LABELS, STATUS_QUOTE, STATUS_RUNNING
from app.services import audit_service, chantier_service as cs, permissions as perms, settings_service
from app.ui.dialogs.chantier_dialog import ChantierDialog, _money
from app.ui.state import AppState
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, make_card, page_title, warn
from app.utils.helpers import format_money


class NewChantierDialog(QDialog):
    def __init__(self, parent=None, quote: bool = False):
        super().__init__(parent)
        self.quote = quote
        self.setWindowTitle(t("Nouveau devis") if quote else t("Nouveau marché"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=460, min_height=380, preferred_width=560, preferred_height=520)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText(t("Ex. Construction villa Zongo"))
        self.client = QComboBox()
        self.client.setEditable(True)
        self.client.addItem("", None)
        for c in ClientController.list():
            self.client.addItem(c.name, c.id)
        self.client.setCurrentIndex(0)
        self.location = QLineEdit()
        self.start = QDateEdit(QDate.currentDate())
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat("dd/MM/yyyy")
        self.end = QDateEdit(QDate.currentDate().addMonths(3))
        self.end.setCalendarPopup(True)
        self.end.setDisplayFormat("dd/MM/yyyy")
        self.amount = _money()
        self.retention = _money()
        self.retention.setDecimals(1)
        self.retention.setMaximum(100)
        self.retention.setSuffix(" %")
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(70)
        form.addRow(t("Nom du chantier"), self.name)
        form.addRow(t("Client"), self.client)
        form.addRow(t("Lieu"), self.location)
        form.addRow(t("Début"), self.start)
        form.addRow(t("Fin prévue"), self.end)
        form.addRow(t("Montant convenu") if not quote else t("Montant du devis (ou ajoutez des lignes ensuite)"), self.amount)
        form.addRow(t("Retenue de garantie"), self.retention)
        form.addRow(t("Notes"), self.notes)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _dt(edit: QDateEdit) -> datetime:
        d = edit.date()
        return datetime(d.year(), d.month(), d.day())

    def values(self) -> dict:
        text = self.client.currentText().strip()
        client_id = self.client.currentData() if self.client.findText(text) >= 0 and text else None
        return dict(name=self.name.text(), client_id=client_id, client_label=text, location=self.location.text(), start_date=self._dt(self.start),
                    end_planned=self._dt(self.end), amount=self.amount.value(), notes=self.notes.toPlainText(), retention_pct=self.retention.value(),
                    status=STATUS_QUOTE if self.quote else STATUS_RUNNING)


class ChantiersPage(QWidget):
    HEADERS = ["N°", "Chantier", "Client", "Statut", "Marché", "Encaissé", "Reste à encaisser", "Dépensé", "Marge", "Avancement"]

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.can_manage = state.can(perms.MANAGE_CHANTIERS)
        self.can_finance = state.can(perms.VIEW_CHANTIER_FINANCE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(page_title(t("Chantiers")))
        self.kpi = QLabel()
        self.kpi.setTextFormat(Qt.TextFormat.RichText)
        self.kpi.setWordWrap(True)
        self.kpi_card = make_card(self.kpi)
        layout.addWidget(self.kpi_card)
        self.kpi_card.setVisible(self.can_finance)
        bar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem(t("Tous les statuts"), None)
        for key, label in STATUS_LABELS.items():
            self.filter.addItem(t(label), key)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("Rechercher un chantier, un client, un lieu…"))
        new_market = QPushButton(t("+ Nouveau marché"))
        new_market.setObjectName("Primary")
        new_quote = QPushButton(t("+ Nouveau devis"))
        new_market.clicked.connect(lambda: self._new(False))
        new_quote.clicked.connect(lambda: self._new(True))
        for b in (new_market, new_quote):
            b.setEnabled(self.can_manage)
        bar.addWidget(self.filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(new_quote)
        bar.addWidget(new_market)
        layout.addLayout(bar)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([t(h) for h in self.HEADERS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 240)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(lambda _i: self._open())
        layout.addWidget(self.table, 1)
        if not self.can_finance:
            for col in (4, 5, 6, 8):
                self.table.setColumnHidden(col, True)
        row = QHBoxLayout()
        open_btn = QPushButton(t("Ouvrir le chantier"))
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self._open)
        self.delete_btn = QPushButton(t("Supprimer"))
        self.delete_btn.setObjectName("Danger")
        self.delete_btn.clicked.connect(self._delete)
        self.delete_btn.setEnabled(self.can_manage)
        row.addWidget(open_btn)
        row.addStretch()
        row.addWidget(self.delete_btn)
        layout.addLayout(row)
        self.filter.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)

    def _user(self) -> tuple:
        return self.state.user_id, getattr(self.state.current_user, "username", "")

    def _new(self, quote: bool) -> None:
        dlg = NewChantierDialog(self, quote)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            cid = cs.create(user_id=self.state.user_id, **dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Chantier créé", "Chantier", dlg.name.text(), *self._user())
        self.refresh()
        self.state.data_changed.emit()
        ChantierDialog(self.state, cid, self).exec()
        self.refresh()

    def _current_id(self):
        row = self.table.currentRow()
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def _open(self) -> None:
        cid = self._current_id()
        if cid:
            ChantierDialog(self.state, cid, self).exec()
            self.refresh()

    def _delete(self) -> None:
        cid = self._current_id()
        if not cid or not confirm(self, t("Supprimer ce chantier ? (impossible s'il a des dépenses ou des encaissements)")):
            return
        try:
            cs.delete(cid)
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Chantier supprimé", "Chantier", str(cid), *self._user())
        self.refresh()

    def refresh(self) -> None:
        cur = settings_service.get_shop_info().currency or "FCFA"
        rows = cs.list_summaries(self.filter.currentData(), self.search.text())
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            cells = [(s.number, False), (s.name, False), ("", False), (t(STATUS_LABELS.get(s.status, s.status)), False), (format_money(s.contract, cur), True),
                     (format_money(s.received, cur), True), (format_money(s.remaining_to_receive, cur), True), (format_money(s.spent, cur), True),
                     (format_money(s.margin, cur), True), (f"{s.progress_pct:g} %", True)]
            for c, (text, right) in enumerate(cells):
                item = QTableWidgetItem(text)
                if right:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, s.chantier_id)
                if c == 8 and s.margin < 0:
                    item.setForeground(Qt.GlobalColor.red)
                self.table.setItem(r, c, item)
            if s.alerts:
                self.table.item(r, 1).setToolTip("\n".join(s.alerts))
                self.table.item(r, 1).setText("⚠ " + s.name)
        self._fill_clients(rows)
        if self.can_finance:
            now = datetime.now()
            month_start = datetime(now.year, now.month, 1)
            g = cs.global_result(month_start)
            overall = cs.global_result()
            self.kpi.setText(
                f"<b>{t('Chantiers en cours')}</b> : {overall.running} &nbsp;·&nbsp; <b>{t('En perte')}</b> : <span style='color:#b91c1c'>{overall.losing}</span> &nbsp;·&nbsp; "
                f"<b>{t('Reste à recevoir')}</b> : {format_money(overall.receivable, cur)} &nbsp;·&nbsp; <b>{t('Dettes fournisseurs')}</b> : {format_money(overall.supplier_debt, cur)}<br/>"
                f"<b>{t('Ce mois')}</b> : {t('encaissé')} {format_money(g.received, cur)} − {t('payé chantiers')} {format_money(g.spent_paid, cur)} − {t('charges générales (loyer, électricité…)')} "
                f"{format_money(g.overheads, cur)} = <b>{format_money(g.net_cash, cur)}</b>")

    def _fill_clients(self, rows) -> None:
        from sqlalchemy import select
        from app.database.connection import session_scope
        from app.models.chantier import Chantier
        with session_scope() as session:
            labels = {c.id: c.client_label for c in session.scalars(select(Chantier))}
        for r in range(self.table.rowCount()):
            cid = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            self.table.setItem(r, 2, QTableWidgetItem(labels.get(cid, "")))
