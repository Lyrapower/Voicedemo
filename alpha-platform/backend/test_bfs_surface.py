"""BFS surface reconcile — unit tests."""
from __future__ import annotations

import unittest

import bfs_surface


class BfsSurfaceTest(unittest.TestCase):
    def test_reconcile_raw_equals_surface_plus_filtered(self):
        rows = [
            {"sym": "TSLA", "bid": 6.3, "ask": 6.44, "score": 53.9},
            {"sym": "NFLX", "bid": 1.11, "ask": 1.15, "score": 48.2},
            {"sym": "NVDA", "bid": 1.0, "ask": 1.1, "score": 40.0},
        ]
        wl = ["NVDA", "PLTR", "AMZN", "NOW"]
        rec = bfs_surface.reconcile_bfs_rows(rows, wl, surface_deny=frozenset({"TSLA", "GOOGL"}))
        self.assertEqual(rec["raw_n"], 3)
        self.assertEqual(rec["surface_n"], 1)
        self.assertEqual(rec["excluded"], ["NFLX", "TSLA"])
        self.assertEqual(rec["raw_n"], rec["surface_n"] + len(rec["surface_filtered"]))


if __name__ == "__main__":
    unittest.main()
