"""America/Los_Angeles calendar window — midnight, exclusive end, DST, year wrap."""
from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from code_task.cloud_store_tools import pdt_calendar_window, _pdt_recent_window

PT = ZoneInfo("America/Los_Angeles")


class TestPdtRecentWindow(unittest.TestCase):
    def test_midnight_sides_and_exclusive_end(self):
        now = datetime(2026, 9, 10, 18, 0, tzinfo=PT)
        lo, hi, label = pdt_calendar_window(1, now=now)
        start = datetime(2026, 9, 10, 0, 0, tzinfo=PT)
        end = datetime(2026, 9, 11, 0, 0, tzinfo=PT)
        self.assertEqual(lo, start.timestamp())
        self.assertEqual(hi, end.timestamp())
        self.assertIn("[", label)
        self.assertIn(")", label)
        self.assertLess(start.timestamp(), end.timestamp())

    def test_days_two_covers_prior_calendar_day(self):
        now = datetime(2026, 9, 10, 8, 0, tzinfo=PT)
        lo, hi, _ = pdt_calendar_window(2, now=now)
        self.assertEqual(lo, datetime(2026, 9, 9, 0, 0, tzinfo=PT).timestamp())
        self.assertEqual(hi, datetime(2026, 9, 11, 0, 0, tzinfo=PT).timestamp())

    def test_year_wrap(self):
        now = datetime(2026, 1, 1, 0, 30, tzinfo=PT)
        lo, hi, _ = pdt_calendar_window(2, now=now)
        self.assertEqual(lo, datetime(2025, 12, 31, 0, 0, tzinfo=PT).timestamp())
        self.assertEqual(hi, datetime(2026, 1, 2, 0, 0, tzinfo=PT).timestamp())

    def test_spring_forward_23h_day(self):
        now = datetime(2026, 3, 8, 12, 0, tzinfo=PT)
        lo, hi, _ = pdt_calendar_window(1, now=now)
        self.assertEqual(hi - lo, 23 * 3600)

    def test_fall_back_25h_day(self):
        now = datetime(2026, 11, 1, 12, 0, tzinfo=PT)
        lo, hi, _ = pdt_calendar_window(1, now=now)
        self.assertEqual(hi - lo, 25 * 3600)

    def test_naive_now_rejected(self):
        with self.assertRaises(ValueError):
            pdt_calendar_window(1, now=datetime(2026, 9, 10, 12, 0))

    def test_unix_override_kept(self):
        lo, hi, label = _pdt_recent_window(
            {"start_ts": "1000", "end_ts": "2000"},
            now=datetime(2026, 9, 10, 12, 0, tzinfo=PT),
        )
        self.assertEqual(lo, 1000.0)
        self.assertEqual(hi, 2000.0)
        self.assertIn("unix-override", label)


if __name__ == "__main__":
    unittest.main()
