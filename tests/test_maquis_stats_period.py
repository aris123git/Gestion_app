"""Tests périodes stats Maquis (parité DateRanges Android)."""

import unittest
from datetime import date, datetime

from app.services.maquis_stats_period import StatsPeriod, bounds_for


class MaquisStatsPeriodTestCase(unittest.TestCase):
    def test_today_bounds(self) -> None:
        ref = datetime(2026, 3, 15, 14, 30)
        start, end = bounds_for(StatsPeriod.TODAY, now=ref)
        self.assertEqual(start.date(), date(2026, 3, 15))
        self.assertEqual(end.date(), date(2026, 3, 15))

    def test_week_is_seven_days(self) -> None:
        ref = datetime(2026, 3, 15, 10, 0)
        start, end = bounds_for(StatsPeriod.WEEK, now=ref)
        self.assertEqual((end.date() - start.date()).days, 6)

    def test_custom_range_order(self) -> None:
        start, end = bounds_for(
            StatsPeriod.CUSTOM_RANGE,
            custom_from=date(2026, 1, 10),
            custom_to=date(2026, 1, 5),
        )
        self.assertLessEqual(start.date(), end.date())


if __name__ == "__main__":
    unittest.main()
