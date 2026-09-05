"""Tests for near-miss aggregation (B5)."""
from __future__ import annotations

import unittest

from aether_filter_patch import Candidate, RejectionLogger


class NearMissAggregationTests(unittest.TestCase):
    def test_merge_kill_rules_per_contract(self) -> None:
        logger = RejectionLogger(log_dir="/tmp/aether_test_rejections")
        cand = Candidate(
            symbol="META",
            strike=675.0,
            expiry="2026-07-24",
            dte=10,
            spot=670.0,
            delta=0.4,
            gamma=0.0073,
            theta=-0.5,
            iv=0.5,
            bid=10.0,
            ask=11.0,
            volume=100,
            open_interest=500,
            quote_source="indicative",
            score=51.36,
        )
        logger.log(cand, "gamma", 0.0073, 0.01)
        logger.log(cand, "premium", 1440.5, 1000.0)
        summary = logger.summary(top_n=5)
        self.assertEqual(len(summary["near_miss_top"]), 1)
        row = summary["near_miss_top"][0]
        self.assertEqual(row["symbol"], "META")
        self.assertIn("gamma", row["kill_rule"])
        self.assertIn("premium", row["kill_rule"])
        self.assertIn("kill_summary", row)
        logger.close()


if __name__ == "__main__":
    unittest.main()
