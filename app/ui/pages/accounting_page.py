"""Page Comptabilité (partie double, plan SYSCOHADA simplifié)."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from app.controllers.report_controller import period_bounds
from app.i18n import t
from app.reports.accounting_export import export_accounting_excel, export_accounting_pdf
from app.services import accounting_service as acc
from app.services import audit_service, settings_service
from app.services.chart_of_accounts import CHART, PRESETS, account_label
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, page_title, warn
from app.ui.widgets.money_spin import MoneySpinBox
from app.utils.helpers import format_money

_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels([t(h) for h in headers])
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill(table: QTableWidget, rows, money_cols=(), bold_rows=(), blank_zero=True) -> None:
    currency = settings_service.get_currency()
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if c in money_cols and isinstance(value, (int, float)):
                text = format_money(value, currency) if (value or not blank_zero) else ''
            else:
                text = '' if value is None else str(value)
            item = QTableWidgetItem(text)
            if c in money_cols:
                item.setTextAlignment(_RIGHT)
            if r in bold_rows:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            table.setItem(r, c, item)


class ManualEntryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t('Nouvelle écriture manuelle'))
        form = QFormLayout(self)
        self.preset = QComboBox()
        self.preset.addItem(t('— Écriture libre —'), None)
        for label, debit, credit in PRESETS:
            self.preset.addItem(t(label), (label, debit, credit))
        self.preset.currentIndexChanged.connect(self._apply_preset)
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.label = QLineEdit()
        self.debit = QComboBox()
        self.credit = QComboBox()
        for code, name in sorted(CHART.items()):
            self.debit.addItem(f'{code} — {name}', code)
            self.credit.addItem(f'{code} — {name}', code)
        self.amount = MoneySpinBox()
        self.amount.setRange(0, 1000000000000)
        self.amount.setDecimals(3)
        form.addRow(t('Modèle'), self.preset)
        form.addRow(t('Date'), self.day)
        form.addRow(t('Libellé'), self.label)
        form.addRow(t('Compte débité'), self.debit)
        form.addRow(t('Compte crédité'), self.credit)
        form.addRow(t('Montant'), self.amount)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _apply_preset(self) -> None:
        data = self.preset.currentData()
        if data:
            label, debit, credit = data
            self.label.setText(t(label))
            self.debit.setCurrentIndex(self.debit.findData(debit))
            self.credit.setCurrentIndex(self.credit.findData(credit))
            if debit == '311' and credit == '101':
                amount, first = acc.suggested_opening_stock()
                self.amount.setValue(amount)
                self.day.setDate(QDate(first.year, first.month, first.day))

    def values(self):
        d = self.day.date()
        return date(d.year(), d.month(), d.day()), self.label.text(), self.debit.currentData(), self.credit.currentData(), self.amount.value()


class AccountingPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._data: dict | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(page_title(t('Comptabilité')))
        controls = QHBoxLayout()
        self.period = QComboBox()
        self.period.addItems(['Journalier', 'Hebdomadaire', 'Mensuel', 'Annuel', 'Personnalisé'])
        self.period.setCurrentText('Mensuel')
        self.period.currentTextChanged.connect(self._period_changed)
        self.start = QDateEdit(QDate.currentDate())
        self.end = QDateEdit(QDate.currentDate())
        for w in (self.start, self.end):
            w.setCalendarPopup(True)
        go = QPushButton(t('Générer'))
        go.setObjectName('Primary')
        go.clicked.connect(self._generate)
        controls.addWidget(QLabel(t('Période :')))
        controls.addWidget(self.period)
        controls.addWidget(QLabel(t('Du')))
        controls.addWidget(self.start)
        controls.addWidget(QLabel(t('Au')))
        controls.addWidget(self.end)
        controls.addWidget(go)
        controls.addStretch()
        layout.addLayout(controls)
        self.warning = QLabel('')
        self.warning.setStyleSheet('color: #b91c1c;')
        self.warning.setWordWrap(True)
        self.warning.hide()
        layout.addWidget(self.warning)

        self.tabs = QTabWidget()
        self.result_table = _table(['Libellé', 'Montant'])
        self.sheet_table = _table(['Compte', 'Intitulé', 'Montant'])
        self.journal_table = _table(acc.JOURNAL_HEADERS)
        ledger = QWidget()
        lv = QVBoxLayout(ledger)
        lv.setContentsMargins(0, 8, 0, 0)
        self.account_combo = QComboBox()
        self.account_combo.currentIndexChanged.connect(self._show_ledger)
        lv.addWidget(self.account_combo)
        self.ledger_table = _table(['Date', 'Journal', 'Pièce', 'Libellé', 'Débit', 'Crédit', 'Solde'])
        lv.addWidget(self.ledger_table)
        self.balance_table = _table(['Compte', 'Intitulé', 'Ouverture débit', 'Ouverture crédit', 'Mouvements débit', 'Mouvements crédit', 'Solde débit', 'Solde crédit'])
        self.vat_table = _table(['Libellé', 'Montant'])
        self.cash_table = _table(['Compte', 'Intitulé', 'Ouverture', 'Entrées', 'Sorties', 'Solde'])
        manual = QWidget()
        mv = QVBoxLayout(manual)
        mv.setContentsMargins(0, 8, 0, 0)
        hint = QLabel(t("Écritures manuelles : capital, stock initial, dépôt en banque, prélèvements… Les ventes, achats, dépenses et règlements sont comptabilisés automatiquement."))
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #64748b; font-size: 12px;')
        mv.addWidget(hint)
        self.manual_table = _table(['Date', 'Libellé', 'Débit', 'Crédit', 'Montant'])
        mv.addWidget(self.manual_table)
        mb = QHBoxLayout()
        mb.addStretch()
        add = QPushButton(t('Nouvelle écriture'))
        add.setObjectName('Primary')
        add.clicked.connect(self._add_manual)
        delete = QPushButton(t('Supprimer la sélection'))
        delete.setObjectName('Danger')
        delete.clicked.connect(self._delete_manual)
        mb.addWidget(add)
        mb.addWidget(delete)
        mv.addLayout(mb)
        self._manual_ids: list[int] = []
        for widget, label in ((self.result_table, 'Résultat'), (self.sheet_table, 'Bilan'), (self.journal_table, 'Journal'), (ledger, 'Grand livre'),
                              (self.balance_table, 'Balance'), (self.vat_table, 'TVA'), (self.cash_table, 'Trésorerie'), (manual, 'Écritures manuelles')):
            self.tabs.addTab(widget, t(label))
        layout.addWidget(self.tabs, 1)
        note = QLabel(t("Plan comptable simplifié inspiré du SYSCOHADA. Écritures générées automatiquement depuis vos opérations. Les avoirs et ajustements de stock ne sont pas comptabilisés ; dépenses et achats payés sont portés en caisse."))
        note.setWordWrap(True)
        note.setStyleSheet('color: #64748b; font-size: 12px;')
        layout.addWidget(note)
        actions = QHBoxLayout()
        actions.addStretch()
        pdf = QPushButton(t('Exporter PDF'))
        pdf.clicked.connect(self._export_pdf)
        xls = QPushButton(t('Exporter Excel'))
        xls.clicked.connect(self._export_excel)
        actions.addWidget(pdf)
        actions.addWidget(xls)
        layout.addLayout(actions)
        self._period_changed(self.period.currentText())

    def refresh(self) -> None:
        self._generate()

    def _period_changed(self, kind: str) -> None:
        custom = kind == 'Personnalisé'
        self.start.setEnabled(custom)
        self.end.setEnabled(custom)
        if not custom:
            s, e = period_bounds(kind)
            self.start.setDate(QDate(s.year, s.month, s.day))
            self.end.setDate(QDate(e.year, e.month, e.day))

    def _range(self):
        s, e = self.start.date(), self.end.date()
        return date(s.year(), s.month(), s.day()), date(e.year(), e.month(), e.day())

    def _generate(self) -> None:
        start, end = self._range()
        data = self._data = acc.build(start, end)
        ir = acc.income_rows(data)
        _fill(self.result_table, [(l, a) for l, a, _b in ir], money_cols=(1,), bold_rows={i for i, r in enumerate(ir) if r[2]}, blank_zero=False)
        sheet = data['sheet']
        rows = [('ACTIF', '', None)] + list(sheet['assets']) + [('', 'TOTAL ACTIF', sheet['total_assets']), ('PASSIF', '', None)] + list(sheet['liabilities']) + [('', 'TOTAL PASSIF', sheet['total_liabilities'])]
        bold = {i for i, r in enumerate(rows) if r[0] in ('ACTIF', 'PASSIF') or str(r[1]).startswith('TOTAL')}
        _fill(self.sheet_table, rows, money_cols=(2,), bold_rows=bold, blank_zero=False)
        _fill(self.journal_table, data['journal'], money_cols=(6, 7))
        current = self.account_combo.currentData()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for acct in data['ledger']:
            self.account_combo.addItem(f'{acct} — {account_label(acct)}', acct)
        if current is not None and self.account_combo.findData(current) >= 0:
            self.account_combo.setCurrentIndex(self.account_combo.findData(current))
        self.account_combo.blockSignals(False)
        self._show_ledger()
        _fill(self.balance_table, data['balance'], money_cols=(2, 3, 4, 5, 6, 7))
        vat = data['vat']
        _fill(self.vat_table, [('TVA collectée (4431)', vat['collected']), ('TVA déductible (4452)', vat['deductible']), ('TVA À PAYER', vat['due'])], money_cols=(1,), bold_rows={2}, blank_zero=False)
        _fill(self.cash_table, data['cash']['rows'], money_cols=(2, 3, 4, 5), blank_zero=False)
        self._load_manual()
        messages = []
        if data['unbalanced']:
            messages.append(t('Attention : écritures déséquilibrées : ') + ', '.join(data['unbalanced'][:10]))
        if any(code == '311' for code, _l, _v in data['sheet']['liabilities']):
            messages.append(t("Le stock comptable est négatif : saisissez le stock initial (onglet Écritures manuelles → Nouvelle écriture → « Stock initial », le montant est proposé automatiquement)."))
        if messages:
            self.warning.setText('\n'.join(messages))
            self.warning.show()
        else:
            self.warning.hide()

    def _show_ledger(self) -> None:
        if not self._data:
            return
        acct = self.account_combo.currentData()
        _fill(self.ledger_table, self._data['ledger'].get(acct, []), money_cols=(4, 5, 6))

    def _load_manual(self) -> None:
        rows = acc.list_manual_entries()
        self._manual_ids = [r[0] for r in rows]
        _fill(self.manual_table, [r[1:] for r in rows], money_cols=(4,))

    def _add_manual(self) -> None:
        dialog = ManualEntryDialog(self)
        if not dialog.exec():
            return
        day, label, debit, credit, amount = dialog.values()
        try:
            entry_id = acc.add_manual_entry(day, label, debit, credit, amount, getattr(self.state, 'user_id', None))
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action('Écriture manuelle', 'Comptabilité', f'#{entry_id} {debit}/{credit} {amount}', getattr(self.state, 'user_id', None), getattr(getattr(self.state, 'current_user', None), 'username', ''))
        self._generate()

    def _delete_manual(self) -> None:
        row = self.manual_table.currentRow()
        if row < 0 or row >= len(self._manual_ids):
            return
        if not confirm(self, t('Supprimer cette écriture manuelle ?')):
            return
        acc.delete_manual_entry(self._manual_ids[row])
        self._generate()

    def _ensure(self) -> dict:
        if self._data is None:
            self._generate()
        return self._data

    def _export_pdf(self) -> None:
        info(self, f'Comptabilité PDF générée :\n{export_accounting_pdf(self._ensure())}')

    def _export_excel(self) -> None:
        info(self, f'Comptabilité Excel générée :\n{export_accounting_excel(self._ensure())}')
