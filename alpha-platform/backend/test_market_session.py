"""market_session RTH + /api/health closed overlay."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


class MarketSessionTests(unittest.TestCase):
    def test_weekend_closed(self) -> None:
        import market_session as ms

        sat = dt.datetime(2026, 9, 5, 12, 0, tzinfo=ET)
        self.assertFalse(ms.is_trading_day(sat.date()))
        self.assertFalse(ms.is_rth(sat))

    def test_holiday_closed(self) -> None:
        import market_session as ms

        # 2026-09-07 Labor Day
        d = dt.date(2026, 9, 7)
        self.assertFalse(ms.is_trading_day(d))
        self.assertFalse(ms.is_rth(dt.datetime(2026, 9, 7, 11, 0, tzinfo=ET)))

    def test_weekday_rth(self) -> None:
        import market_session as ms

        tue = dt.datetime(2026, 9, 8, 10, 0, tzinfo=ET)
        self.assertTrue(ms.is_trading_day(tue.date()))
        self.assertTrue(ms.is_rth(tue))
        self.assertFalse(ms.is_rth(dt.datetime(2026, 9, 8, 16, 0, tzinfo=ET)))
        self.assertFalse(ms.is_rth(dt.datetime(2026, 9, 8, 9, 29, tzinfo=ET)))


class HealthClosedOverlayTests(unittest.TestCase):
    def test_data_equity_closed_when_not_rth(self) -> None:
        import app as ap

        fake_rows = [("data_equity", 1, "empty", "0/5")]
        with mock.patch.object(ap.market_session, "is_rth", return_value=False), mock.patch.object(
            ap.db, "check_integrity", return_value=None
        ), mock.patch.object(ap.db, "conn") as conn:
            c = mock.MagicMock()
            c.execute.return_value.fetchall.return_value = fake_rows
            conn.return_value = c
            h = ap.health()
        self.assertEqual(h["components"]["data_equity"]["status"], "closed")

    def test_data_equity_untouched_in_rth(self) -> None:
        import app as ap

        fake_rows = [("data_equity", 1, "ok", "5/5")]
        with mock.patch.object(ap.market_session, "is_rth", return_value=True), mock.patch.object(
            ap.db, "check_integrity", return_value=None
        ), mock.patch.object(ap.db, "conn") as conn:
            c = mock.MagicMock()
            c.execute.return_value.fetchall.return_value = fake_rows
            conn.return_value = c
            h = ap.health()
        self.assertEqual(h["components"]["data_equity"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
