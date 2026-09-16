"""Périodes stats Maquis (parité tablette StatsPeriod + DateRanges)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Optional, Tuple


class StatsPeriod(str, Enum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    WEEK = "week"
    MONTH = "month"
    CUSTOM_DAY = "custom_day"
    CUSTOM_RANGE = "custom_range"
    ALL = "all"

    @property
    def label(self) -> str:
        return {
            StatsPeriod.TODAY: "Aujourd'hui",
            StatsPeriod.YESTERDAY: "Hier",
            StatsPeriod.WEEK: "7 jours",
            StatsPeriod.MONTH: "30 jours",
            StatsPeriod.CUSTOM_DAY: "Jour…",
            StatsPeriod.CUSTOM_RANGE: "Intervalle…",
            StatsPeriod.ALL: "Tout",
        }[self]


def _day_bounds(d: date) -> Tuple[datetime, datetime]:
    start = datetime.combine(d, time.min)
    end = datetime.combine(d, time.max)
    return start, end


def bounds_for(
    period: StatsPeriod,
    *,
    custom_day: Optional[date] = None,
    custom_from: Optional[date] = None,
    custom_to: Optional[date] = None,
    now: Optional[datetime] = None,
) -> Tuple[datetime, datetime]:
    """Bornes inclusives alignées sur l'app Android Maquiscaisse."""
    ref = (now or datetime.now()).date()
    if period == StatsPeriod.TODAY:
        return _day_bounds(ref)
    if period == StatsPeriod.YESTERDAY:
        return _day_bounds(ref - timedelta(days=1))
    if period == StatsPeriod.WEEK:
        end_d = ref
        start_d = ref - timedelta(days=6)
        return datetime.combine(start_d, time.min), datetime.combine(end_d, time.max)
    if period == StatsPeriod.MONTH:
        end_d = ref
        start_d = ref - timedelta(days=29)
        return datetime.combine(start_d, time.min), datetime.combine(end_d, time.max)
    if period == StatsPeriod.CUSTOM_DAY:
        d = custom_day or ref
        return _day_bounds(d)
    if period == StatsPeriod.CUSTOM_RANGE:
        d_from = custom_from or ref
        d_to = custom_to or ref
        if d_to < d_from:
            d_from, d_to = d_to, d_from
        return datetime.combine(d_from, time.min), datetime.combine(d_to, time.max)
    if period == StatsPeriod.ALL:
        return datetime(1970, 1, 1), datetime(9999, 12, 31, 23, 59, 59, 999000)
    return _day_bounds(ref)


@dataclass
class MaquisPeriodSelection:
    period: StatsPeriod = StatsPeriod.TODAY
    custom_day: Optional[date] = None
    custom_from: Optional[date] = None
    custom_to: Optional[date] = None

    def bounds(self) -> Tuple[datetime, datetime]:
        return bounds_for(
            self.period,
            custom_day=self.custom_day,
            custom_from=self.custom_from,
            custom_to=self.custom_to,
        )

    def subtitle(self) -> str:
        return f"{self.period.label} — CA, coûts et bénéfices"
