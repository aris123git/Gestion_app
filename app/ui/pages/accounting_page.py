"""Page Comptabilité (partie double, plan SYSCOHADA simplifié)."""
from __future__ import annotations

import re
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
                               QProgressBar, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from app.i18n import t
from app.reports.accounting_export import export_accounting_excel, export_accounting_pdf
from app.services import accounting_service as acc
from app.services import audit_service, settings_service
from app.services.chart_of_accounts import CHART, PRESETS, account_label
from app.ui.state import AppState
from app.ui.widgets.batch import enable_multi, run_batch, selected_rows
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.ui.widgets.period_picker import PeriodPicker
from app.ui.widgets.money_spin import MoneySpinBox
from app.utils.helpers import format_money

_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels([t(h) for h in headers])
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)
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
    def __init__(self, parent=None, stock_initial: bool = False):
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
        if stock_initial:
            for i in range(self.preset.count()):
                d = self.preset.itemData(i)
                if d and d[1] == '311' and d[2] == '101':
                    self.preset.setCurrentIndex(i)
                    break

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


_CODE = re.compile(r'^(.*?)\s*\(([0-9][0-9…]*)\)$')
_BAR = 'QProgressBar {background: #e2e8f0; border: none; border-radius: 5px;} QProgressBar::chunk {background: #2563eb; border-radius: 5px;}'


def _hint(text: str) -> QLabel:
    lab = QLabel(t(text))
    lab.setWordWrap(True)
    lab.setStyleSheet('color: #64748b; font-size: 12px;')
    return lab


def _wrap(*widgets: QWidget) -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for w in widgets:
        lay.addWidget(w, 1 if isinstance(w, QTableWidget) else 0)
    return make_card(box)


class AccountingPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._data: dict | None = None
        self._manual_ids: list[int] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(page_title(t('Comptabilité')))
        sub = QLabel(t('Vos comptes, générés automatiquement depuis vos ventes, achats et dépenses'))
        sub.setStyleSheet('color: #64748b;')
        titles.addWidget(sub)
        top.addLayout(titles)
        top.addStretch()
        export = QPushButton(t('Exporter'))
        export.setObjectName('Primary')
        menu = QMenu(export)
        menu.addAction(t('PDF'), self._export_pdf)
        menu.addAction(t('Excel'), self._export_excel)
        export.setMenu(menu)
        top.addWidget(export)
        layout.addLayout(top)
        self.picker = PeriodPicker()
        self.picker.mode.setCurrentIndex(self.picker.mode.findData('month'))
        self.picker.changed.connect(self._generate)
        prow = QHBoxLayout()
        prow.addWidget(self.picker)
        prow.addStretch(1)
        layout.addLayout(prow)
        self.banner = QWidget()
        self.banner.setStyleSheet('background: #fef3c7; border: 1px solid #fcd34d; border-radius: 10px;')
        bl = QHBoxLayout(self.banner)
        self.warning = QLabel('')
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet('color: #92400e; border: none; background: transparent;')
        self.stock_button = QPushButton(t('Saisir le stock initial'))
        self.stock_button.clicked.connect(lambda: self._add_manual(stock_initial=True))
        bl.addWidget(self.warning, 1)
        bl.addWidget(self.stock_button)
        self.banner.hide()
        layout.addWidget(self.banner)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.k = {}
        for key in ('Ventes', 'Marge commerciale', 'Charges', 'Résultat net', 'Trésorerie'):
            lab = QLabel()
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setMinimumHeight(44)
            self.k[key] = lab
            cards.addWidget(make_card(lab), 1)
        layout.addLayout(cards)

        self.tabs = QTabWidget()
        self.result_table = _table(['Libellé', 'Compte', 'Montant'])
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        res_row = QWidget()
        rr = QHBoxLayout(res_row)
        rr.setContentsMargins(0, 8, 0, 0)
        rr.setSpacing(12)
        title = QLabel('<b>' + t('Compte de résultat') + "</b> <span style='color:#64748b'>· " + t('ce que vous avez gagné et dépensé') + '</span>')
        title.setTextFormat(Qt.TextFormat.RichText)
        rr.addWidget(_wrap(title, self.result_table), 3)
        spend = QWidget()
        self.spend = QVBoxLayout(spend)
        self.spend.setContentsMargins(0, 0, 0, 0)
        self.spend.setSpacing(4)
        rr.addWidget(make_card(spend), 2)
        self.sheet_table = _table(['Compte', 'Intitulé', 'Montant'])
        self.cash_table = _table(['Compte', 'Intitulé', 'Ouverture', 'Entrées', 'Sorties', 'Solde'])
        self.vat_table = _table(['Libellé', 'Montant'])
        self.journal_table = _table(acc.JOURNAL_HEADERS)
        self.ledger_table = _table(['Date', 'Journal', 'Pièce', 'Libellé', 'Débit', 'Crédit', 'Solde'])
        self.balance_table = _table(['Compte', 'Intitulé', 'Ouverture débit', 'Ouverture crédit', 'Mouvements débit', 'Mouvements crédit', 'Solde débit', 'Solde crédit'])
        self.account_combo = QComboBox()
        self.account_combo.currentIndexChanged.connect(self._show_ledger)
        ledger = QWidget()
        lv = QVBoxLayout(ledger)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.account_combo)
        lv.addWidget(self.ledger_table)
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self.journal_table)
        self.detail_stack.addWidget(ledger)
        self.detail_stack.addWidget(self.balance_table)
        self.detail_kind = QComboBox()
        for label in ('Journal : toutes les écritures, jour par jour', 'Grand livre : les écritures regroupées compte par compte', 'Balance : le total de chaque compte'):
            self.detail_kind.addItem(t(label))
        self.detail_kind.currentIndexChanged.connect(self.detail_stack.setCurrentIndex)
        detail = _wrap(self.detail_kind, self.detail_stack)
        self.manual_table = _table(['Date', 'Libellé', 'Débit', 'Crédit', 'Montant'])
        enable_multi(self.manual_table)
        mb = QHBoxLayout()
        mb.addStretch()
        add = QPushButton(t('Nouvelle écriture'))
        add.setObjectName('Primary')
        add.clicked.connect(lambda: self._add_manual())
        delete = QPushButton(t('Supprimer la sélection'))
        delete.setObjectName('DangerOutline')
        delete.clicked.connect(self._delete_manual)
        mb.addWidget(add)
        mb.addWidget(delete)
        mbw = QWidget()
        mbw.setLayout(mb)
        mb.setContentsMargins(0, 0, 0, 0)
        manual = _wrap(_hint("Écritures manuelles : capital, stock initial, dépôt en banque, prélèvements… Les ventes, achats, dépenses et règlements sont comptabilisés automatiquement."), self.manual_table, mbw)
        self.tab_defs = [
            ('Résultat', res_row, None),
            ('Bilan', _wrap(_hint("Ce que vous possédez (actif) et ce que vous devez (passif) à la fin de la période."), self.sheet_table), None),
            ('Trésorerie', _wrap(_hint("L'argent en caisse, en banque et en mobile money : entrées, sorties et solde."), self.cash_table), None),
            ('TVA', _wrap(_hint("TVA collectée sur vos ventes, moins la TVA déductible sur vos achats."), self.vat_table), 'vat'),
            ('Détail comptable', detail, None),
            ('Écritures manuelles', manual, None),
        ]
        layout.addWidget(self.tabs, 1)
        note = _hint("Plan comptable simplifié inspiré du SYSCOHADA. Les avoirs et ajustements de stock ne sont pas comptabilisés ; dépenses et achats payés sont portés en caisse.")
        layout.addWidget(note)
        self._build_tabs(show_vat=True)

    def _build_tabs(self, show_vat: bool) -> None:
        keep = self.tabs.tabText(self.tabs.currentIndex()) if self.tabs.count() else ''
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for label, widget, cond in self.tab_defs:
            if cond == 'vat' and not show_vat:
                continue
            self.tabs.addTab(widget, t(label))
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == keep:
                self.tabs.setCurrentIndex(i)
        self.tabs.blockSignals(False)

    def refresh(self) -> None:
        self._generate()

    def _range(self):
        return self.picker.period()

    def _generate(self) -> None:
        start, end = self._range()
        data = self._data = acc.build(start, end)
        currency = settings_service.get_currency()
        inc = data['income']
        net = inc['result']
        vals = {'Ventes': inc['sales'], 'Marge commerciale': inc['margin'], 'Charges': inc['charges_total'], 'Résultat net': net, 'Trésorerie': data['cash']['total']}
        for key, lab in self.k.items():
            color = '#0f172a'
            if key == 'Résultat net':
                color = '#15803d' if net >= 0 else '#b91c1c'
            lab.setText(f"<span style='color:#64748b;font-size:12px'>{t(key)}</span><br><b style='font-size:18px;color:{color}'>{format_money(vals[key], currency)}</b>")
        # résultat : libellé / compte / montant
        ir = acc.income_rows(data)
        rows = []
        for label, amount, bold in ir:
            m = _CODE.match(label)
            rows.append((m.group(1) if m else label, m.group(2) if m else '', amount))
        _fill(self.result_table, rows, money_cols=(2,), bold_rows={i for i, r in enumerate(ir) if r[2]}, blank_zero=False)
        last = self.result_table.rowCount() - 1
        if last >= 0:
            tint = QColor('#f0fdf4' if net >= 0 else '#fef2f2')
            for c in range(self.result_table.columnCount()):
                it = self.result_table.item(last, c)
                if it:
                    it.setBackground(QBrush(tint))
            amt = self.result_table.item(last, 2)
            if amt:
                amt.setForeground(QBrush(QColor('#15803d' if net >= 0 else '#b91c1c')))
        self._fill_spend(inc, currency)
        sheet = data['sheet']
        srows = [('ACTIF', '', None)] + list(sheet['assets']) + [('', 'TOTAL ACTIF', sheet['total_assets']), ('PASSIF', '', None)] + list(sheet['liabilities']) + [('', 'TOTAL PASSIF', sheet['total_liabilities'])]
        bold = {i for i, r in enumerate(srows) if r[0] in ('ACTIF', 'PASSIF') or str(r[1]).startswith('TOTAL')}
        _fill(self.sheet_table, srows, money_cols=(2,), bold_rows=bold, blank_zero=False)
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
        self._build_tabs(show_vat=bool(settings_service.get_vat_rate() > 0 or abs(vat['collected']) > 0.001 or abs(vat['deductible']) > 0.001))
        self._load_manual()
        messages = []
        stock_missing = any(code == '311' for code, _l, _v in data['sheet']['liabilities'])
        if data['unbalanced']:
            messages.append(t('Attention : écritures déséquilibrées : ') + ', '.join(data['unbalanced'][:10]))
        if stock_missing:
            messages.append(t("Le stock de départ n'est pas encore enregistré : le bilan est incomplet."))
        self.stock_button.setVisible(stock_missing)
        self.warning.setText('\n'.join(messages))
        self.banner.setVisible(bool(messages))

    def _fill_spend(self, inc: dict, currency: str) -> None:
        while self.spend.count():
            it = self.spend.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.spend.addWidget(QLabel('<b>' + t("Où part l'argent") + '</b>'))
        items = []
        if inc['purchases'] > 0:
            items.append((t('Achats de marchandises'), inc['purchases']))
        items += [(label, amount) for _a, label, amount in inc['charges'] if amount > 0]
        total = sum(v for _l, v in items)
        if not items:
            self.spend.addWidget(QLabel(t('Aucune dépense sur la période.')))
        for label, value in sorted(items, key=lambda lv: -lv[1]):
            pct = value / total * 100 if total else 0
            row = QWidget()
            row.setStyleSheet('background: transparent;')
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 8, 0, 0)
            a, b = QLabel(label), QLabel(f'<b>{format_money(value, currency)} · {pct:.0f} %</b>')
            b.setTextFormat(Qt.TextFormat.RichText)
            h.addWidget(a, 1)
            h.addWidget(b)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(round(pct)))
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(_BAR)
            self.spend.addWidget(row)
            self.spend.addWidget(bar)
        self.spend.addStretch(1)

    def _show_ledger(self) -> None:
        if not self._data:
            return
        acct = self.account_combo.currentData()
        _fill(self.ledger_table, self._data['ledger'].get(acct, []), money_cols=(4, 5, 6))

    def _load_manual(self) -> None:
        rows = acc.list_manual_entries()
        self._manual_ids = [r[0] for r in rows]
        _fill(self.manual_table, [r[1:] for r in rows], money_cols=(4,))

    def _add_manual(self, stock_initial: bool = False) -> None:
        dialog = ManualEntryDialog(self, stock_initial=stock_initial)
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
        rows = [r for r in selected_rows(self.manual_table) if r < len(self._manual_ids)]
        if not rows:
            warn(self, t('Sélectionnez une écriture.'))
            return
        items = [(self._manual_ids[r], self.manual_table.item(r, 1).text() if self.manual_table.item(r, 1) else '') for r in rows]
        run_batch(self, t('Supprimer {n} écriture(s) manuelle(s) ?'), items, acc.delete_manual_entry, t('écriture(s) supprimée(s)'))
        self._generate()

    def _ensure(self) -> dict:
        if self._data is None:
            self._generate()
        return self._data

    def _export_pdf(self) -> None:
        info(self, f'Comptabilité PDF générée :\n{export_accounting_pdf(self._ensure())}')

    def _export_excel(self) -> None:
        info(self, f'Comptabilité Excel générée :\n{export_accounting_excel(self._ensure())}')
