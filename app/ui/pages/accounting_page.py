"""Page Comptabilité (simplifiée) : résultat, journal, TVA, trésorerie."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget

from app.controllers.report_controller import period_bounds
from app.i18n import t
from app.reports.accounting_export import export_accounting_excel, export_accounting_pdf
from app.services import accounting_service as acc
from app.services import settings_service
from app.ui.state import AppState
from app.ui.widgets.helpers import info, page_title
from app.utils.helpers import format_money


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels([t(h) for h in headers])
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


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
        self.tabs = QTabWidget()
        self.result_table = _table(['Libellé', 'Montant'])
        self.journal_table = _table(acc.JOURNAL_HEADERS)
        self.vat_table = _table(['Taux %', 'Ventes TTC', 'Hors taxe', 'TVA collectée'])
        self.cash_table = _table(['Libellé', 'Montant'])
        for table, label in ((self.result_table, 'Résultat'), (self.journal_table, 'Journal'), (self.vat_table, 'TVA'), (self.cash_table, 'Trésorerie')):
            self.tabs.addTab(table, t(label))
        layout.addWidget(self.tabs, 1)
        self.note = QLabel(t("Les montants de TVA sont ceux inclus dans les prix de vente. Le coût d'achat provient du prix d'achat enregistré au moment de la vente."))
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color: #64748b; font-size: 12px;')
        layout.addWidget(self.note)
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

    @staticmethod
    def _fill(table: QTableWidget, rows, money_cols=(), bold_rows=()) -> None:
        currency = settings_service.get_currency()
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if c in money_cols and isinstance(value, (int, float)):
                    text = format_money(value, currency) if value else ''
                elif isinstance(value, float):
                    text = f'{value:g}'
                else:
                    text = '' if value is None else str(value)
                item = QTableWidgetItem(text)
                if c in money_cols:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if r in bold_rows:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                table.setItem(r, c, item)

    def _generate(self) -> None:
        start, end = self._range()
        data = self._data = acc.build(start, end)
        rr = acc.result_rows(data)
        currency = settings_service.get_currency()
        self.result_table.setRowCount(len(rr))
        for r, (label, amount, bold) in enumerate(rr):
            for c, text in enumerate((label, format_money(amount, currency))):
                item = QTableWidgetItem(text)
                if c == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if bold:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.result_table.setItem(r, c, item)
        self._fill(self.journal_table, data['journal'], money_cols=(6, 7, 8))
        self._fill(self.vat_table, data['vat'], money_cols=(1, 2, 3))
        cash = data['cash']
        rows = [('ENTRÉES', None)] + list(cash['inflows']) + [('Total entrées', cash['total_in']), ('SORTIES', None)] + list(cash['outflows']) + [
            ('Total sorties', cash['total_out']), ('SOLDE DE LA PÉRIODE', cash['balance']), ('Achats non réglés (à crédit)', cash['purchases_on_credit'])]
        bold = {i for i, (label, _a) in enumerate(rows) if label.isupper() or label.startswith('Total')}
        self._fill(self.cash_table, rows, money_cols=(1,), bold_rows=bold)

    def _ensure(self) -> dict:
        if self._data is None:
            self._generate()
        return self._data

    def _export_pdf(self) -> None:
        path = export_accounting_pdf(self._ensure())
        info(self, f'Comptabilité PDF générée :\n{path}')

    def _export_excel(self) -> None:
        path = export_accounting_excel(self._ensure())
        info(self, f'Comptabilité Excel générée :\n{path}')
