#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest.mock import patch

import schedule_catchup as sc


class TestScheduleCatchup(unittest.TestCase):
    def test_lane_order_covers_all_stale_keys(self) -> None:
        keys = {spec.stale_key for spec in sc.LANES}
        self.assertEqual(keys, set(sc.STALE_KEYS))

    @patch("daily_stack_verify.verify_and_alert", return_value={"ok": True, "checks": []})
    @patch("schedule_catchup.ensure_gateway8501", return_value=(True, "ok"))
    @patch("schedule_catchup.run_lane_once", return_value=(True, "ok"))
    @patch("schedule_catchup.agent_pid", return_value=12345)
    @patch("daemon_schedule.minutes_past_slot", return_value=10)
    @patch("schedule_catchup._cooldown_active", return_value=False)
    @patch("pipeline_health.pipeline_health")
    def test_stale_lane_triggers_once(self, mock_ph, _cd, _mps, _pid, mock_run, _gw, _verify) -> None:
        mock_ph.return_value = {
            "today": "2026-07-16",
            "stale_post_market": True,
            "stale_premarket_grid": False,
            "stale_premarket_sonnet": False,
            "stale_sonnet_earnings": False,
            "stale_paper_crypto_cli": False,
            "stale_paper_daily": False,
            "stale_offpool": False,
            "stale_offpool_coach": False,
        }
        result = sc.catchup_pass(grace_minutes=3, retry_minutes=10)
        lane_actions = [a for a in result["actions"] if a.get("lane") == "stale_post_market"]
        self.assertEqual(len(lane_actions), 1)
        mock_run.assert_called_once()

    @patch("daily_stack_verify.verify_and_alert", return_value={"ok": True, "checks": []})
    @patch("schedule_catchup.ensure_gateway8501", return_value=(True, "ok"))
    @patch("pipeline_health.pipeline_health")
    def test_not_stale_no_lane_action(self, mock_ph, _gw, _verify) -> None:
        mock_ph.return_value = {
            "today": "2026-07-16",
            "stale_post_market": False,
            "stale_premarket_grid": False,
            "stale_premarket_sonnet": False,
            "stale_sonnet_earnings": False,
            "stale_paper_crypto_cli": False,
            "stale_paper_daily": False,
            "stale_offpool": False,
            "stale_offpool_coach": False,
        }
        result = sc.catchup_pass(grace_minutes=0, retry_minutes=10)
        lane_actions = [a for a in result["actions"] if a.get("lane", "").startswith("stale_")]
        self.assertEqual(lane_actions, [])


if __name__ == "__main__":
    unittest.main()
