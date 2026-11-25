"""Cloche : alertes automatiques + rappels saisis à la main + choix des alertes."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from app.i18n import t
from app.services import notification_service as ns
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, dialog_header_banner, warn

ICONS = {ns.KIND_STOCK: "📦", ns.KIND_DEBT: "💳", ns.KIND_PROSPECT: "🛵", ns.KIND_REMINDER: "⏰"}


class ReminderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Nouveau rappel"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(dialog_header_banner(t("Nouveau rappel")))
        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(20, 16, 20, 20)
        outer.addWidget(body, 1)
        self.text = QLineEdit()
        self.text.setPlaceholderText(t("ex. Payer le loyer"))
        self.due = QDateEdit(QDate.currentDate())
        self.due.setCalendarPopup(True)
        self.due.setDisplayFormat("dd/MM/yyyy")
        self.repeat = QComboBox()
        for key, label in ns.REPEATS:
            self.repeat.addItem(t(label), key)
        form.addRow(t("Rappel"), self.text)
        form.addRow(t("Date"), self.due)
        form.addRow(t("Répéter"), self.repeat)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self):
        d = self.due.date()
        from datetime import date
        return self.text.text(), date(d.year(), d.month(), d.day()), self.repeat.currentData()


class AlertsDialog(QDialog):
    def __init__(self, parent, can):
        super().__init__(parent)
        self.can = can
        self.target = None            # (page, ref_id) à ouvrir après fermeture
        self.setWindowTitle(t("Alertes et rappels"))
        fit_dialog_to_screen(self, min_width=520, min_height=460, preferred_width=620, preferred_height=560)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QWidget()
        header.setObjectName("DialogHeaderBanner")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 14, 20, 16)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 16px; font-weight: 800;")
        header_layout.addWidget(self.title)
        outer.addWidget(header)
        v = QVBoxLayout()
        v.setContentsMargins(20, 16, 20, 16)
        outer.addLayout(v, 1)
        self.list = QListWidget()
        self.list.setStyleSheet('QListWidget::item { padding: 8px 6px; }')
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        self.list.itemDoubleClicked.connect(lambda *_: self._open())
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.b_open = QPushButton(t("Ouvrir"))
        self.b_open.setObjectName("Primary")
        self.b_done = QPushButton(t("Fait"))
        self.b_del = QPushButton(t("Supprimer le rappel"))
        add = QPushButton(t("+ Rappel"))
        self.b_open.clicked.connect(self._open)
        self.b_done.clicked.connect(self._done)
        self.b_del.clicked.connect(self._delete)
        add.clicked.connect(self._add)
        for b in (self.b_open, self.b_done, self.b_del):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(add)
        v.addLayout(row)
        v.addWidget(QLabel(f"<b>{t('Alertes à afficher')}</b>"))
        self.checks = {}
        for kind in ns.KINDS:
            c = QCheckBox(t(ns.LABELS[kind]))
            c.setChecked(ns.is_enabled(kind))
            c.toggled.connect(lambda val, k=kind: (ns.set_enabled(k, val), self._fill()))
            self.checks[kind] = c
            v.addWidget(c)
        close = QPushButton(t("Fermer"))
        close.clicked.connect(self.accept)
        v.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        items = ns.alerts(self.can, include_upcoming=True)
        due = [a for a in items if not a.upcoming]
        for a in due:
            self._add_item(a)
        later = [a for a in items if a.upcoming]
        if later:
            head = QListWidgetItem(t("À venir"))
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            self.list.addItem(head)
            for a in later:
                self._add_item(a)
        self.title.setText(f"{len(due)} " + (t("alerte") if len(due) <= 1 else t("alertes")) if due else t("Aucune alerte pour le moment"))
        self._sync_buttons()

    def _add_item(self, a: ns.Alert) -> None:
        it = QListWidgetItem(f"{ICONS.get(a.kind, '•')}  {a.text}")
        it.setData(Qt.ItemDataRole.UserRole, a)
        if a.upcoming:
            it.setForeground(QColor("#94a3b8"))
        self.list.addItem(it)

    def _current(self):
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def _sync_buttons(self) -> None:
        a = self._current()
        self.b_open.setEnabled(a is not None and bool(a.page))
        self.b_done.setEnabled(a is not None and a.reminder_id is not None)
        self.b_del.setEnabled(a is not None and a.reminder_id is not None)

    def _open(self) -> None:
        a = self._current()
        if a is not None and a.page:
            self.target = (a.page, a.ref_id)
            self.accept()

    def _done(self) -> None:
        a = self._current()
        if a is not None and a.reminder_id is not None:
            ns.mark_done(a.reminder_id)
            self._fill()

    def _delete(self) -> None:
        a = self._current()
        if a is not None and a.reminder_id is not None and confirm(self, t("Supprimer ce rappel ?")):
            ns.delete_reminder(a.reminder_id)
            self._fill()

    def _add(self) -> None:
        dlg = ReminderDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            ns.add_reminder(*dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.checks[ns.KIND_REMINDER].setChecked(True)
        self._fill()
