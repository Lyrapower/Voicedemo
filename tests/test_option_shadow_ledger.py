"""PKG_PRESTART_v1 step 5 — option shadow ledger (mocked Theta)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness_resident"))

from harness.option_shadow_ledger import extract_legs, settle_leg  # noqa: E402


class TestShadowLedger(unittest.TestCase):
    def test_exit_before_entry_rejected(self):
        r = settle_leg({
            "ticker": "NVDA", "direction": "call",
            "entry_window_pst": "13:00-14:00",
            "exit_window_pst": "09:00-10:00",
        }, "2026-09-08", opener=lambda u: ("[]", "0"*64))
        self.assertEqual(r["unsettled"], "exit_before_entry")
        self.assertIsNone(r.get("pnl"))

    def test_missing_ticker_unsettled(self):
        r = settle_leg({
            "ticker": "NO_SUCH", "direction": "call",
            "entry_window_pst": "07:00-09:00",
            "exit_window_pst": "11:00-13:00",
        }, "2026-09-08")
        self.assertEqual(r["unsettled"], "no_chain")
        self.assertIsNone(r.get("pnl"))

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
