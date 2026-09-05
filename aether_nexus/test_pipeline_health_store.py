#!/usr/bin/env python3
from __future__ import annotations

import unittest

from pipeline_health import pipeline_health


class TestPipelineHealthStore(unittest.TestCase):
    def test_grid_and_scan_read_store(self) -> None:
        ph = pipeline_health()
        grid = ph["premarket_grid"]
        self.assertEqual(grid.get("store_last_success_date"), "2026-07-15")
        self.assertFalse(ph["stale_premarket_grid"])
        self.assertTrue(ph["pool_scan"]["last_success_ts"])

    def test_sonnet_reads_store(self) -> None:
        sonnet = pipeline_health()["premarket_sonnet"]
        self.assertEqual(sonnet.get("store_last_success_date"), "2026-07-15")


if __name__ == "__main__":
    unittest.main()
