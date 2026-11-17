"""Sélecteur de période : Jour / Mois / Trimestre / Année / Personnalisé.

Expose `start_edit` et `end_edit` (QDateEdit) et le signal `changed`. Par défaut : aujourd'hui."""

from __future__ import annotations

import calendar
from datetime import date

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import QComboBox, QDateEdit, QHBoxLayout, QLabel, QWidget

from app.i18n import t

MONTHS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
MODES = [("day", "Jour"), ("month", "Mois"), ("quarter", "Trimestre"), ("year", "Année"), ("custom", "Personnalisé")]


def _edit() -> QDateEdit:
    e = QDateEdit()
    e.setCalendarPopup(True)
    e.setDisplayFormat("dd/MM/yyyy")
    e.setDate(QDate.currentDate())
    return e


class PeriodPicker(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.mode = QComboBox()
        for key, label in MODES:
            self.mode.addItem(t(label), key)
        self.sub = QComboBox()
        self.year = QComboBox()
        for y in range(date.today().year + 1, 2019, -1):
            self.year.addItem(str(y), y)
        self.year.setCurrentIndex(self.year.findData(date.today().year))
        self.start_edit, self.end_edit = _edit(), _edit()
        self.l_from, self.l_to = QLabel(t("Du")), QLabel(t("au"))
        self.range_label = QLabel()
        self.range_label.setStyleSheet("color: #64748b;")
        for w in (self.mode, self.sub, self.year, self.l_from, self.start_edit, self.l_to, self.end_edit, self.range_label):
            lay.addWidget(w)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.sub.currentIndexChanged.connect(self._apply)
        self.year.currentIndexChanged.connect(self._apply)
        self.start_edit.dateChanged.connect(lambda *_: self._edit_changed("start"))
        self.end_edit.dateChanged.connect(lambda *_: self._edit_changed("end"))
        self._fill_sub()
        self._layout_for_mode()

    # -- lecture ---------------------------------------------------------------------------------
    def current_mode(self) -> str:
        return self.mode.currentData()

    def period(self) -> tuple[date, date]:
        a, b = self.start_edit.date(), self.end_edit.date()
        return date(a.year(), a.month(), a.day()), date(b.year(), b.month(), b.day())

    # -- interne ---------------------------------------------------------------------------------
    def _fill_sub(self) -> None:
        mode = self.current_mode()
        end = self.end_edit.date()
        self.sub.blockSignals(True)
        self.sub.clear()
        if mode == "month":
            for i, m in enumerate(MONTHS, 1):
                self.sub.addItem(t(m), i)
            self.sub.setCurrentIndex(end.month() - 1)
        elif mode == "quarter":
            for q in range(1, 5):
                self.sub.addItem(f"{t('Trimestre')} {q}", q)
            self.sub.setCurrentIndex((end.month() - 1) // 3)
        self.sub.blockSignals(False)
        self.year.blockSignals(True)
        self.year.setCurrentIndex(max(0, self.year.findData(end.year())))
        self.year.blockSignals(False)

    def _layout_for_mode(self) -> None:
        mode = self.current_mode()
        self.sub.setVisible(mode in ("month", "quarter"))
        self.year.setVisible(mode in ("month", "quarter", "year"))
        self.l_from.setVisible(mode == "custom")
        self.start_edit.setVisible(mode == "custom")
        self.l_to.setVisible(mode in ("custom",))
        self.end_edit.setVisible(mode in ("day", "custom"))
        self.range_label.setVisible(mode in ("month", "quarter", "year"))
        a, b = self.period()
        self.range_label.setText(f"{t('Du')} {a:%d/%m/%Y} {t('au')} {b:%d/%m/%Y}")

    def _set(self, a: QDate, b: QDate) -> None:
        for e, d in ((self.start_edit, a), (self.end_edit, b)):
            e.blockSignals(True)
            e.setDate(d)
            e.blockSignals(False)

    def _mode_changed(self) -> None:
        mode = self.current_mode()
        if mode == "day":
            e = self.end_edit.date()
            self._set(e, e)
        self._fill_sub()
        self._apply()

    def _apply(self, *_a) -> None:
        mode = self.current_mode()
        y = self.year.currentData() or date.today().year
        if mode == "month" and self.sub.currentData():
            m = self.sub.currentData()
            self._set(QDate(y, m, 1), QDate(y, m, calendar.monthrange(y, m)[1]))
        elif mode == "quarter" and self.sub.currentData():
            q = self.sub.currentData()
            m1, m2 = 3 * q - 2, 3 * q
            self._set(QDate(y, m1, 1), QDate(y, m2, calendar.monthrange(y, m2)[1]))
        elif mode == "year":
            self._set(QDate(y, 1, 1), QDate(y, 12, 31))
        self._layout_for_mode()
        self.changed.emit()

    def _edit_changed(self, which: str) -> None:
        mode = self.current_mode()
        a, b = self.start_edit.date(), self.end_edit.date()
        if mode == "day":
            self._set(b, b)
        elif a > b:                                    # personnalisé : garder début <= fin
            self._set(b, b) if which == "end" else self._set(a, a)
        self._layout_for_mode()
        self.changed.emit()
