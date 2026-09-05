"""Unit tests for SURFACE_DOCTOR v1 checks."""
from __future__ import annotations

import unittest

import surface_doctor as sd


class TestSurfaceDoctor(unittest.TestCase):
    def test_c3_rejects_incomplete_card(self) -> None:
        row = {"sym": "TSLA", "bid": 6.0, "ask": 6.5, "score": 42.0}
        out = sd.check_c3([row], quarantine=False)
        self.assertEqual(out["status"], "FAIL")
        self.assertTrue(out["detail"])

    def test_c3_passes_quarantine_no_cards(self) -> None:
        row = {"sym": "TSLA", "score": 42.0}
        out = sd.check_c3([row], quarantine=True)
        self.assertEqual(out["status"], "OK")

    def test_c2_count_mismatch(self) -> None:
        plat = {
            "rows": [],
            "audit": {
                "windows": {
                    "AM": {
                        "candidates": 2,
                        "decisions": 0,
                        "filtered": [{"symbol": "GOOGL", "reason": "missing bid/ask"}],
                    }
                }
            },
            "bfs": {"windows": {"AM": {"rows": [{}, {}]}}},
        }
        out = sd.check_c2("AM", plat)
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(out["detail"]["header_hits"], 2)

    def test_c5_requires_isolation_badge(self) -> None:
        plat = {
            "quarantine": {"active": True, "scan_event_ids": [46435]},
            "header_contract": {"am_hits": 2, "am_isolation_badge": False},
            "audit": {"windows": {"AM": {"quarantine": True}}},
        }
        out = sd.check_c5("2026-07-27", "AM", plat, 46435)
        self.assertEqual(out["status"], "FAIL")
        self.assertIn("裸计数", out["detail"][0])


if __name__ == "__main__":
    unittest.main()
