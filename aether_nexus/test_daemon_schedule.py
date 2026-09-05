#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import unittest

from daemon_schedule import parse_hhmm, slot_due


class TestDaemonSchedule(unittest.TestCase):
    def test_parse_hhmm(self) -> None:
        self.assertEqual(parse_hhmm("06:30"), (6, 30))
        self.assertEqual(parse_hhmm(" 16:35 "), (16, 35))

    def test_slot_due_before(self) -> None:
        now = dt.datetime(2026, 7, 16, 6, 29)
        self.assertFalse(slot_due(now, 6, 30))

    def test_slot_due_at(self) -> None:
        now = dt.datetime(2026, 7, 16, 6, 30)
        self.assertTrue(slot_due(now, 6, 30))

    def test_slot_due_after_misses_exact_minute(self) -> None:
        """Poll at 06:31 still fires — the old exact-minute check would skip the day."""
        now = dt.datetime(2026, 7, 16, 6, 31)
        self.assertTrue(slot_due(now, 6, 30))

    def test_slot_due_later_same_day(self) -> None:
        now = dt.datetime(2026, 7, 16, 16, 45)
        self.assertTrue(slot_due(now, 16, 35))

    def test_minutes_past_slot(self) -> None:
        from daemon_schedule import minutes_past_slot

        now = dt.datetime(2026, 7, 16, 16, 40)
        self.assertEqual(minutes_past_slot(now, 16, 35), 5)
        self.assertEqual(minutes_past_slot(now, 16, 45), 0)


if __name__ == "__main__":
    unittest.main()
