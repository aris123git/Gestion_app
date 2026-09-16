"""Sélecteur de période Maquis (parité PeriodSelector + dates libres)."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDateEdit, QHBoxLayout, QLabel, QPushButton, QWidget

from app.i18n import t
from app.services.maquis_stats_period import MaquisPeriodSelection, StatsPeriod


class MaquisPeriodBar(QWidget):
    period_changed = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._selection = MaquisPeriodSelection()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._buttons: dict[StatsPeriod, QPushButton] = {}
        for period in StatsPeriod:
            btn = QPushButton(period.label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, p=period: self._select_preset(p))
            layout.addWidget(btn)
            self._buttons[period] = btn
        layout.addStretch()
        self._day_label = QLabel(t("Jour"))
        self._day_edit = QDateEdit()
        self._day_edit.setCalendarPopup(True)
        self._day_edit.setDate(date.today())
        self._day_edit.dateChanged.connect(self._on_custom_day)
        self._from_label = QLabel(t("Du"))
        self._from_edit = QDateEdit()
        self._from_edit.setCalendarPopup(True)
        self._from_edit.setDate(date.today())
        self._to_label = QLabel(t("Au"))
        self._to_edit = QDateEdit()
        self._to_edit.setCalendarPopup(True)
        self._to_edit.setDate(date.today())
        self._from_edit.dateChanged.connect(self._on_custom_range)
        self._to_edit.dateChanged.connect(self._on_custom_range)
        for w in (
            self._day_label,
            self._day_edit,
            self._from_label,
            self._from_edit,
            self._to_label,
            self._to_edit,
        ):
            layout.addWidget(w)
        refresh_btn = QPushButton(t("Actualiser"))
        refresh_btn.clicked.connect(lambda: self.period_changed.emit(self._selection))
        layout.addWidget(refresh_btn)
        self._select_preset(StatsPeriod.TODAY, emit=False)
        self._sync_custom_visibility()

    def selection(self) -> MaquisPeriodSelection:
        return self._selection

    def _select_preset(self, period: StatsPeriod, *, emit: bool = True) -> None:
        self._selection.period = period
        for p, btn in self._buttons.items():
            btn.setChecked(p == period)
        self._sync_custom_visibility()
        if emit:
            self.period_changed.emit(self._selection)

    def _sync_custom_visibility(self) -> None:
        p = self._selection.period
        show_day = p == StatsPeriod.CUSTOM_DAY
        show_range = p == StatsPeriod.CUSTOM_RANGE
        for w, show in (
            (self._day_label, show_day),
            (self._day_edit, show_day),
            (self._from_label, show_range),
            (self._from_edit, show_range),
            (self._to_label, show_range),
            (self._to_edit, show_range),
        ):
            w.setVisible(show)

    def _on_custom_day(self) -> None:
        self._selection.custom_day = self._day_edit.date().toPython()
        self._selection.period = StatsPeriod.CUSTOM_DAY
        for p, btn in self._buttons.items():
            btn.setChecked(p == StatsPeriod.CUSTOM_DAY)
        self.period_changed.emit(self._selection)

    def _on_custom_range(self) -> None:
        self._selection.custom_from = self._from_edit.date().toPython()
        self._selection.custom_to = self._to_edit.date().toPython()
        self._selection.period = StatsPeriod.CUSTOM_RANGE
        for p, btn in self._buttons.items():
            btn.setChecked(p == StatsPeriod.CUSTOM_RANGE)
        self.period_changed.emit(self._selection)
