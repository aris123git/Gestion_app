"""Journal d'audit — accessible aux rôles disposant de VIEW_AUDIT."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app.services import audit_service, permissions as perms
from app.ui.state import AppState
from app.ui.widgets.helpers import make_card, page_title, warn
from app.ui.widgets.period_picker import PeriodPicker
from app.utils.helpers import format_datetime

ACTION_STYLE = {
    'Vente': ('#dcfce7', '#166534'),
    'Connexion': ('#f1f5f9', '#475569'),
    'Connexion rapide': ('#f1f5f9', '#475569'),
}


def action_style(action: str) -> tuple[str, str]:
    if action in ACTION_STYLE:
        return ACTION_STYLE[action]
    low = action.lower()
    if 'suppression' in low or 'annul' in low:
        return ('#fee2e2', '#991b1b')
    if 'modification' in low or 'écriture' in low:
        return ('#dbeafe', '#1e40af')
    return ('#f8fafc', '#334155')


class AuditPage(QWidget):
    HEADERS = ['Date et heure', 'Utilisateur', 'Action', 'Détails']

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._logs: list = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(page_title(t("Journal d'audit")))
        self.picker = PeriodPicker()
        self.picker.mode.setCurrentIndex(self.picker.mode.findData('month'))
        self.picker.changed.connect(self.refresh)
        prow = QHBoxLayout()
        prow.addWidget(self.picker)
        prow.addStretch(1)
        layout.addLayout(prow)
        card = QWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(8)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('Rechercher : utilisateur, action, détails…'))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _=None: self._render())
        self.action_filter = QComboBox()
        self.action_filter.currentIndexChanged.connect(lambda _i: self._render())
        self.user_filter = QComboBox()
        self.user_filter.currentIndexChanged.connect(lambda _i: self._render())
        bar.addWidget(self.search, 1)
        bar.addWidget(self.action_filter)
        bar.addWidget(self.user_filter)
        card_layout.addLayout(bar)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([t(h) for h in self.HEADERS])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(360)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        card_layout.addWidget(self.table, 1)
        self.count_label = QLabel('')
        self.count_label.setStyleSheet('color: #64748b; font-size: 12px;')
        card_layout.addWidget(self.count_label)
        layout.addWidget(make_card(card), 1)

    def refresh(self) -> None:
        if not self.state.can(perms.VIEW_AUDIT):
            warn(self, t("Vous n'avez pas l'autorisation de consulter l'audit."))
            return
        start, end = self.picker.period()
        self._logs = audit_service.list_logs(limit=500, start=start, end=end)
        keep_action = self.action_filter.currentData()
        keep_user = self.user_filter.currentData()
        self.action_filter.blockSignals(True)
        self.action_filter.clear()
        self.action_filter.addItem(t('Toutes les actions'), None)
        for action in sorted({log.action for log in self._logs}):
            self.action_filter.addItem(action, action)
        idx = self.action_filter.findData(keep_action)
        self.action_filter.setCurrentIndex(max(idx, 0))
        self.action_filter.blockSignals(False)
        self.user_filter.blockSignals(True)
        self.user_filter.clear()
        self.user_filter.addItem(t('Tous les utilisateurs'), None)
        for username in sorted({log.username for log in self._logs if log.username}):
            self.user_filter.addItem(username, username)
        idx = self.user_filter.findData(keep_user)
        self.user_filter.setCurrentIndex(max(idx, 0))
        self.user_filter.blockSignals(False)
        self._render()

    def _render(self) -> None:
        needle = self.search.text().strip().lower()
        action = self.action_filter.currentData()
        username = self.user_filter.currentData()
        rows = [
            log for log in self._logs
            if (not action or log.action == action)
            and (not username or log.username == username)
            and (not needle or needle in (log.username or '').lower() or needle in (log.action or '').lower() or needle in (log.details or '').lower())
        ]
        self.table.setRowCount(len(rows))
        for r, log in enumerate(rows):
            act = QTableWidgetItem(log.action)
            bg, fg = action_style(log.action)
            act.setBackground(QBrush(QColor(bg)))
            act.setForeground(QBrush(QColor(fg)))
            details = QTableWidgetItem(log.details)
            details.setToolTip(log.details)
            for c, item in enumerate([QTableWidgetItem(format_datetime(log.date)), QTableWidgetItem(log.username), act, details]):
                self.table.setItem(r, c, item)
        self.count_label.setText(f"{len(rows)} {t('entrée(s)')}" + (' · ' + t('500 maximum chargées sur la période — réduisez-la pour voir plus loin dans le détail') if len(self._logs) >= 500 else ''))
