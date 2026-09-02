"""Join /v2/options/contracts OI: real 0 kept; missing → null + oi_source=missing."""
from __future__ import annotations

import json
import unittest

from aether_dryrun import (
    _oi_liquidity_component,
    _oi_missing,
    _parse_contract_oi_field,
    format_message,
    join_contract_open_interest,
)
from aether_grid_emit import _scan_rows
from offpool_coach.stage1_mechanical import gate_liquidity


def _row(occ: str, oi_src: str = "missing") -> dict:
    return {
        "occ": occ,
        "open_interest": None,
        "oi_source": oi_src,
        "oi_unverified": True,
        "volume": 50,
    }


class JoinContractOpenInterestTests(unittest.TestCase):
    def test_hit_keeps_real_zero(self) -> None:
        rows = [_row("PLTR260918C00040000")]
        join_contract_open_interest(rows, {"PLTR260918C00040000": 0})
        self.assertEqual(rows[0]["open_interest"], 0)
        self.assertEqual(rows[0]["oi_source"], "alpaca_contracts")
        self.assertFalse(rows[0]["oi_unverified"])
        self.assertFalse(_oi_missing(rows[0]))

    def test_hit_positive_oi(self) -> None:
        rows = [_row("NVDA260918C00180000")]
        join_contract_open_interest(rows, {"NVDA260918C00180000": 12450})
        self.assertEqual(rows[0]["open_interest"], 12450)
        self.assertEqual(rows[0]["oi_source"], "alpaca_contracts")

    def test_missing_occ_writes_null_not_zero(self) -> None:
        rows = [_row("SMCI260918C00045000")]
        join_contract_open_interest(rows, {"OTHER": 99})
        self.assertIsNone(rows[0]["open_interest"])
        self.assertEqual(rows[0]["oi_source"], "missing")
        self.assertTrue(rows[0]["oi_unverified"])
        self.assertTrue(_oi_missing(rows[0]))
        dumped = json.dumps(rows[0])
        self.assertIn('"open_interest": null', dumped)
        self.assertNotIn('"open_interest": 0', dumped)

    def test_map_none_is_missing_not_zero(self) -> None:
        rows = [_row("IREN260918C00030000")]
        join_contract_open_interest(rows, {"IREN260918C00030000": None})
        self.assertIsNone(rows[0]["open_interest"])
        self.assertEqual(rows[0]["oi_source"], "missing")

    def test_parse_field(self) -> None:
        self.assertEqual(_parse_contract_oi_field("0"), 0)
        self.assertEqual(_parse_contract_oi_field(0), 0)
        self.assertEqual(_parse_contract_oi_field("1842"), 1842)
        self.assertIsNone(_parse_contract_oi_field(None))
        self.assertIsNone(_parse_contract_oi_field(""))

    def test_hardzero_component(self) -> None:
        self.assertEqual(_oi_liquidity_component({"oi_source": "missing", "open_interest": None}), 0.0)
        self.assertEqual(_oi_liquidity_component({"oi_source": "missing_in_snapshot", "open_interest": 0}), 0.0)
        self.assertEqual(_oi_liquidity_component({"oi_source": "alpaca_contracts", "open_interest": 0}), 0.0)
        self.assertEqual(_oi_liquidity_component({"oi_source": "alpaca_contracts", "open_interest": 500}), 1.0)

    def test_emit_writes_null_oi(self) -> None:
        rows = _scan_rows([{
            "symbol": "PLTR",
            "score": 40,
            "open_interest": None,
            "oi_source": "missing",
            "oi_unverified": True,
            "volume": 200,
        }])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["open_interest"])
        self.assertEqual(rows[0]["oi_source"], "missing")
        self.assertTrue(rows[0]["oi_unverified"])

    def test_format_message_na_not_zero(self) -> None:
        msg = format_message([{
            "symbol": "PLTR",
            "score": 40,
            "is_perilla": False,
            "has_earnings_catalyst": False,
            "has_fda": False,
            "score_breakdown": {},
            "underlying_price": 10,
            "underlying_price_source": "test",
            "strike": 12,
            "expiry": "2026-09-18",
            "dte": 17,
            "delta": 0.4,
            "gamma_theta_ratio": 1.0,
            "iv": 0.5,
            "iv_source": "test",
            "hv_rank": 0.5,
            "iv_hv_ratio": 1.0,
            "bid": 1,
            "ask": 1.1,
            "volume": 200,
            "open_interest": None,
            "spread_pct": 0.05,
            "premium_dollars": 105,
            "price_source": "test",
            "stock_data_provider": "fmp",
            "option_data_provider": "alpaca",
        }])
        self.assertIn("OI NA", msg)
        self.assertNotIn("OI 0", msg)

    def test_offpool_gate_treats_missing_source(self) -> None:
        ok, reason, meta = gate_liquidity({
            "spread_pct": 0.04,
            "oi_source": "missing",
            "open_interest": None,
            "bid": 1.0,
            "ask": 1.05,
            "quote_stale": False,
        })
        self.assertTrue(ok)
        self.assertTrue(meta["oi_unverified"])
        self.assertIn("oi_unverified", reason)


if __name__ == "__main__":
    unittest.main()
