"""Page de gestion des dépenses : saisie rapide, période, répartition par catégorie, modification."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import config
from app.controllers.expense_controller import ExpenseController
from app.i18n import t
from app.services import audit_service, permissions as perms, settings_service
from app.ui.state import AppState
from app.ui.widgets.batch import enable_multi, run_batch, selected_rows
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.ui.widgets.money_spin import MoneySpinBox
from app.ui.widgets.period_picker import PeriodPicker
from app.utils.helpers import format_money


class ExpenseDialog(QDialog):
    """Modification d'une dépense."""

    def __init__(self, expense, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t('Modifier la dépense'))
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.category = QComboBox()
        self.category.addItems(config.EXPENSE_CATEGORIES)
        i = self.category.findText(expense.category)
        if i < 0:
            self.category.addItem(expense.category)
            i = self.category.count() - 1
        self.category.setCurrentIndex(i)
        self.label = QLineEdit(expense.label)
        self.amount = MoneySpinBox()
        self.amount.setRange(0, 1000000000)
        self.amount.setDecimals(3)
        self.amount.setValue(float(expense.amount))
        d = expense.date
        self.date = QDateEdit(QDate(d.year, d.month, d.day))
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('dd/MM/yyyy')
        self._time = d.time()
        form.addRow(t('Catégorie'), self.category)
        form.addRow(t('Libellé'), self.label)
        form.addRow(t('Montant'), self.amount)
        form.addRow(t('Date'), self.date)
        row = QHBoxLayout()
        no = QPushButton(t('Annuler'))
        no.clicked.connect(self.reject)
        ok = QPushButton(t('Enregistrer'))
        ok.setObjectName('Success')
        ok.clicked.connect(self.accept)
        row.addWidget(no)
        row.addWidget(ok)
        form.addRow(row)

    def values(self) -> dict:
        q = self.date.date()
        return {'category': self.category.currentText(), 'label': self.label.text().strip(), 'amount': self.amount.value(),
                'date': datetime.combine(date(q.year(), q.month(), q.day()), self._time)}


class ExpensesPage(QWidget):
    HEADERS = ['Date', 'Catégorie', 'Libellé', 'Montant']

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._ids: list[int] = []
        self._cat: Optional[str] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(page_title(t('Dépenses')))
        top.addStretch()
        self.picker = PeriodPicker()
        self.picker.mode.setCurrentIndex(self.picker.mode.findData('month'))
        self.picker.changed.connect(self.refresh)
        top.addWidget(self.picker)
        layout.addLayout(top)
        entry = QWidget()
        entry_layout = QHBoxLayout(entry)
        entry_layout.setContentsMargins(0, 0, 0, 0)
        self.category = QComboBox()
        self.category.addItems(config.EXPENSE_CATEGORIES)
        self.label = QLineEdit()
        self.label.setPlaceholderText(t('Libellé'))
        self.amount = MoneySpinBox()
        self.amount.setRange(0, 1000000000)
        self.amount.setDecimals(3)
        self.amount.setSingleStep(500)
        add = QPushButton(t('Enregistrer la dépense'))
        add.setObjectName('Primary')
        add.clicked.connect(self._add)
        entry_layout.addWidget(self.category, 1)
        entry_layout.addWidget(self.label, 2)
        entry_layout.addWidget(self.amount, 1)
        entry_layout.addWidget(add)
        layout.addWidget(make_card(entry))
        kp = QHBoxLayout()
        self.k_total, self.k_count, self.k_top = QLabel(), QLabel(), QLabel()
        for k in (self.k_total, self.k_count, self.k_top):
            k.setTextFormat(Qt.TextFormat.RichText)
            k.setMinimumHeight(44)
            kp.addWidget(make_card(k), 1)
        layout.addLayout(kp)
        body = QHBoxLayout()
        body.setSpacing(16)
        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('Rechercher un libellé…'))
        self.search.textChanged.connect(lambda _=None: self.refresh())
        self.cat_filter = QComboBox()
        self.cat_filter.currentIndexChanged.connect(self._filter_changed)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.cat_filter)
        left.addLayout(bar)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([t(h) for h in self.HEADERS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QTableWidget.Shape.NoFrame)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setMinimumHeight(260)
        enable_multi(self.table)
        self.table.doubleClicked.connect(self._edit)
        left.addWidget(self.table, 1)
        body.addWidget(make_card(left_w), 3)
        side_w = QWidget()
        side = QVBoxLayout(side_w)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(6)
        side.addWidget(QLabel('<b>' + t('Répartition par catégorie') + '</b>'))
        self.breakdown = QVBoxLayout()
        side.addLayout(self.breakdown)
        hint = QLabel(t('Cliquer une catégorie filtre la liste.'))
        hint.setStyleSheet('color: #64748b;')
        side.addWidget(hint)
        row = QHBoxLayout()
        edit = QPushButton(t('Modifier'))
        edit.clicked.connect(self._edit)
        delete = QPushButton(t('Supprimer'))
        delete.setObjectName('DangerOutline')
        delete.clicked.connect(self._delete)
        row.addWidget(edit)
        row.addWidget(delete)
        row.addStretch(1)
        side.addSpacing(8)
        side.addLayout(row)
        side.addStretch(1)
        body.addWidget(make_card(side_w), 2)
        layout.addLayout(body)
        layout.addStretch(1)

    def _filter_changed(self, *_a) -> None:
        self._cat = self.cat_filter.currentData()
        self.refresh()

    def _set_category(self, cat: Optional[str]) -> None:
        i = self.cat_filter.findData(cat)
        self.cat_filter.setCurrentIndex(max(i, 0))

    def _add(self) -> None:
        if not self.state.can(perms.MANAGE_EXPENSES):
            warn(self, t("Vous n'avez pas l'autorisation d'ajouter une dépense."))
            return
        if self.amount.value() <= 0:
            warn(self, t('Le montant doit être supérieur à zéro.'))
            return
        ExpenseController.create({'category': self.category.currentText(), 'label': self.label.text().strip(), 'amount': self.amount.value()}, user_id=self.state.user_id)
        audit_service.log_action('Dépense', 'Expense', f'{self.category.currentText()} {self.amount.value()}', self.state.user_id, getattr(self.state.current_user, 'username', ''))
        self.label.clear()
        self.amount.setValue(0)
        self.refresh()
        self.state.notify_data_changed()

    def _edit(self, *_a) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            warn(self, t('Sélectionnez une dépense.'))
            return
        if not self.state.can(perms.MANAGE_EXPENSES):
            warn(self, t("Vous n'avez pas l'autorisation de modifier une dépense."))
            return
        expense = next((e for e in self._expenses if e.id == self._ids[row]), None)
        if not expense:
            return
        dlg = ExpenseDialog(expense, self)
        if not dlg.exec():
            return
        v = dlg.values()
        if v['amount'] <= 0:
            warn(self, t('Le montant doit être supérieur à zéro.'))
            return
        try:
            ExpenseController.update(expense.id, v, is_admin=getattr(self.state.current_user, 'role', '') == perms.ROLE_ADMIN, user_id=self.state.user_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action('Modification dépense', 'Expense', f"id={expense.id} {v['category']} {v['amount']}", self.state.user_id, getattr(self.state.current_user, 'username', ''))
        self.refresh()
        self.state.notify_data_changed()

    def _delete_many(self, rows: list[int]) -> None:
        if not self.state.can(perms.MANAGE_EXPENSES):
            warn(self, t("Vous n'avez pas l'autorisation de supprimer une dépense."))
            return
        from app.services import audit_service
        user = getattr(self.state.current_user, 'username', '')
        is_admin = getattr(self.state.current_user, 'role', '') == perms.ROLE_ADMIN

        def one(eid: int) -> None:
            ExpenseController.delete(eid, is_admin=is_admin, user_id=self.state.user_id)
            audit_service.log_action('Suppression dépense', 'Expense', f'id={eid}', self.state.user_id, user)

        items = [(self._ids[r], self.table.item(r, 0).text()) for r in rows]
        if run_batch(self, t("Supprimer {n} dépenses ?"), items, one, t("dépense(s) supprimée(s)")):
            self.refresh()
            self.state.notify_data_changed()

    def _delete(self) -> None:
        rows = selected_rows(self.table)
        if len(rows) > 1:
            return self._delete_many(rows)
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            warn(self, t('Sélectionnez une dépense.'))
            return
        if not self.state.can(perms.MANAGE_EXPENSES):
            warn(self, t("Vous n'avez pas l'autorisation de supprimer une dépense."))
            return
        if confirm(self, t('Supprimer cette dépense ?')):
            expense_id = self._ids[row]
            try:
                ExpenseController.delete(expense_id, is_admin=getattr(self.state.current_user, 'role', '') == perms.ROLE_ADMIN, user_id=self.state.user_id)
            except ValueError as exc:
                warn(self, str(exc))
                return
            from app.services import audit_service
            audit_service.log_action('Suppression dépense', 'Expense', f'id={expense_id}', self.state.user_id, getattr(self.state.current_user, 'username', ''))
            self.refresh()
            self.state.notify_data_changed()

    def refresh(self) -> None:
        cur = settings_service.get_currency()
        d0, d1 = self.picker.period()
        everything = ExpenseController.list(start=d0, end=d1, limit=20000)
        self._expenses = everything
        # répartition par catégorie (sur toute la période, quel que soit le filtre)
        totals: dict[str, float] = {}
        for e in everything:
            totals[e.category] = totals.get(e.category, 0.0) + float(e.amount)
        grand = sum(totals.values())
        self.k_total.setText(f"<span style='color:#64748b'>{t('Dépenses de la période')}</span><br><b style='font-size:18px;color:#b91c1c'>{format_money(grand, cur)}</b>")
        self.k_count.setText(f"<span style='color:#64748b'>{t('Nombre de dépenses')}</span><br><b style='font-size:18px'>{len(everything)}</b>")
        ranked = sorted(totals.items(), key=lambda kv: -kv[1])
        if ranked and grand > 0:
            self.k_top.setText(f"<span style='color:#64748b'>{t('Plus grosse catégorie')}</span><br><b style='font-size:18px'>{ranked[0][0]}</b> <span style='color:#64748b'>({ranked[0][1] / grand * 100:.0f} %)</span>")
        else:
            self.k_top.setText(f"<span style='color:#64748b'>{t('Plus grosse catégorie')}</span><br><b style='font-size:18px'>—</b>")
        # menu de filtre
        keep_cat = self._cat
        self.cat_filter.blockSignals(True)
        self.cat_filter.clear()
        self.cat_filter.addItem(t('Toutes les catégories'), None)
        for cat, _v in ranked:
            self.cat_filter.addItem(cat, cat)
        i = self.cat_filter.findData(keep_cat)
        self.cat_filter.setCurrentIndex(max(i, 0))
        self._cat = self.cat_filter.currentData()
        self.cat_filter.blockSignals(False)
        # barres
        while self.breakdown.count():
            w = self.breakdown.takeAt(0).widget()
            if w:
                w.deleteLater()
        for cat, value in ranked:
            pct = value / grand * 100 if grand else 0
            btn = QPushButton(cat)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet('text-align: left; padding: 0; border: none; background: transparent;' + (' font-weight: 700;' if cat == self._cat else ' font-weight: 400;'))
            btn.clicked.connect(lambda _=False, c=cat: self._set_category(None if self._cat == c else c))
            amt = QLabel(f"<b>{value:,.0f}".replace(',', ' ') + f" · {pct:.0f} %</b>")
            amt.setAlignment(Qt.AlignmentFlag.AlignRight)
            line = QWidget()
            line.setStyleSheet('background: transparent;')
            lh = QHBoxLayout(line)
            lh.setContentsMargins(0, 8, 0, 2)
            lh.addWidget(btn, 1)
            lh.addWidget(amt)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(round(pct)))
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet('QProgressBar {background: #e2e8f0; border: none; border-radius: 5px;} QProgressBar::chunk {background: #2563eb; border-radius: 5px;}')
            self.breakdown.addWidget(line)
            self.breakdown.addWidget(bar)
        # liste filtrée
        needle = self.search.text().strip().lower()
        rows = [e for e in everything if (not self._cat or e.category == self._cat) and (not needle or needle in (e.label or '').lower())]
        keep = self._ids[self.table.currentRow()] if 0 <= self.table.currentRow() < len(self._ids) else None
        self._ids = [e.id for e in rows]
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            amount = QTableWidgetItem(f"{e.amount:,.0f}".replace(',', ' '))
            amount.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for c, it in enumerate([QTableWidgetItem(e.date.strftime('%d/%m')), QTableWidgetItem(e.category), QTableWidgetItem(e.label), amount]):
                self.table.setItem(r, c, it)
        if keep in self._ids:
            self.table.setCurrentCell(self._ids.index(keep), 0)
