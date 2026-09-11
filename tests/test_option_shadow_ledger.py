"""PKG_PRESTART_v5 — option shadow ledger."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness_resident"))

from harness.option_shadow_ledger import extract_legs, settle_leg, Theta  # noqa: E402


class TestShadowLedger(unittest.TestCase):
    def test_exit_before_entry_rejected(self):
        th = Theta(opener=lambda u: "[]")
        r = settle_leg(th, {
            "ticker": "NVDA", "direction": "call",
            "entry_window_pst": "13:00-14:00",
            "exit_window_pst": "09:00-10:00",
        }, date(2026, 9, 8))
        self.assertEqual(r["status"], "rejected:exit_before_entry")
        self.assertIsNone(r.get("net"))

    def test_missing_ticker_unsettled(self):
        th = Theta(opener=lambda u: "[]")
        r = settle_leg(th, {
            "ticker": "NO_SUCH", "direction": "call",
            "entry_window_pst": "07:00-09:00",
            "exit_window_pst": "11:00-13:00",
        }, date(2026, 9, 8))
        self.assertEqual(r["status"], "unsettled:no_chain")
        self.assertIsNone(r.get("net"))

    def test_extract_candidates_and_hedge(self):
        brief = {
            "candidates": [
                {"empty": True, "ticker": "X"},
                {"ticker": "BABA", "direction": "call",
                 "strategy": {"entry_window_pst": "07:00-09:00", "exit_window_pst": "11:30-13:00"}},
            ],
            "hedge": {"legs": [{"ticker": "GLD", "direction": "call",
                                "entry_window_pst": "07:00-08:00", "exit_window_pst": "12:00-13:00"}]},
        }
        legs = extract_legs(brief)
        self.assertEqual([x["ticker"] for x in legs], ["BABA", "GLD"])


if __name__ == "__main__":
    unittest.main()
