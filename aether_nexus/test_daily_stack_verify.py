"""Tests for automated daily stack QA."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import daily_stack_verify as dsv


class TestDailyStackVerify(unittest.TestCase):
    @patch("daily_stack_verify._store_count", return_value=2)
    @patch("daily_stack_verify._launchd_running", return_value=True)
    @patch("daily_stack_verify._tailscale_health", return_value=(True, "host.ts.net"))
    @patch("daily_stack_verify._http_ok", return_value=True)
    @patch("daily_stack_verify._fetch_bytes", return_value=b'const PAGE_VER="2026-08-02-mem-archive";')
    @patch("post_market_summary_daemon.ground_from_store_scan", return_value={"top_symbol": "NVDA"})
    def test_run_passes_on_weekday(self, _ground, *_mocks):
        with patch.dict("os.environ", {"OFFPOOL_COACH_REQUIRED": "0"}, clear=False):
            result = dsv.run_daily_stack_verify(trade_date="2026-07-20")
        self.assertTrue(result["ok"], result.get("failures"))

    @patch("daily_stack_verify._launchd_running", return_value=True)
    @patch("daily_stack_verify._tailscale_health", return_value=(True, "host.ts.net"))
    @patch("daily_stack_verify._http_ok", return_value=True)
    @patch("daily_stack_verify._fetch_bytes", return_value=b"PAGE_VER=x")
    @patch("post_market_summary_daemon.ground_from_store_scan", return_value={"top_symbol": "NVDA"})
    def test_retired_coach_missing_is_warn_not_fail(self, _ground, *_mocks):
        def _count(kind, **_kw):
            return 0 if kind == "aether_offpool_coach" else 2

        with patch("daily_stack_verify._store_count", side_effect=_count):
            with patch.dict("os.environ", {"OFFPOOL_COACH_REQUIRED": "0"}, clear=False):
                result = dsv.run_daily_stack_verify(trade_date="2026-08-11")
        self.assertTrue(result["ok"], result.get("failures"))
        self.assertFalse(result.get("offpool_coach_required"))
        self.assertTrue(any("offpool_coach" in w for w in (result.get("warnings") or [])))

    @patch("daily_stack_verify._http_ok", return_value=False)
    def test_gateway_down_fails(self, _mock_http):
        result = dsv.run_daily_stack_verify(trade_date="2026-07-20")
        self.assertFalse(result["ok"])
        self.assertTrue(any("gateway8501" in f for f in result["failures"]))

    @patch("aether_shared.send_notification")
    def test_alert_cooldown(self, mock_send):
        with patch.object(dsv, "_read_state", return_value={"last_fail_date": "2026-07-20", "last_alert_ts": "2099-01-01T00:00:00+00:00"}):
            alerted = dsv.maybe_alert_verify_result({"ok": False, "trade_date": "2026-07-20", "failures": ["x"]})
        self.assertFalse(alerted)
        mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
