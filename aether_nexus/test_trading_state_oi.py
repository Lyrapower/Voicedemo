"""TRADING v12 signal row must carry contracts OI (null stays null)."""
from __future__ import annotations

import unittest

from trading_state import _signal_from_row


class TradingStateOiTests(unittest.TestCase):
    def test_passes_alpaca_contracts_oi(self) -> None:
        sig = _signal_from_row({
            "sym": "UBER",
            "bid": 1.5,
            "ask": 1.56,
            "strike": 77.5,
            "expiry": "2026-09-18",
            "dte": 17,
            "score": 66.65,
            "volume": 253,
            "open_interest": 5320,
            "oi_source": "alpaca_contracts",
            "oi_unverified": False,
            "dir": 1,
        })
        self.assertIsNotNone(sig)
        self.assertEqual(sig["open_interest"], 5320)
        self.assertEqual(sig["oi_source"], "alpaca_contracts")
        self.assertEqual(sig["volume"], 253)

    def test_missing_oi_stays_none(self) -> None:
        sig = _signal_from_row({
            "sym": "FAKE",
            "bid": 1.0,
            "ask": 1.1,
            "strike": 10,
            "open_interest": None,
            "oi_source": "missing",
            "oi_unverified": True,
            "dir": 1,
        })
        self.assertIsNone(sig["open_interest"])
        self.assertEqual(sig["oi_source"], "missing")


if __name__ == "__main__":
    unittest.main()
