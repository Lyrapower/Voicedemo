"""Render contract smoke test — Aether TRADING v12 OI bit.

Locks the OI render branch in grid-sovereign-runtime/gateway/static/aether_trading_v12.html
(lines ~566-567) so it can't be silently inverted or removed:

    if(item.open_interest!=null) bits.push(`OI ${item.open_interest}`);
    else if(item.oi_unverified||item.oi_source==="missing") bits.push("OI NA");

Two render fixtures (砥 §C 13):
  1. open_interest=0            -> "OI 0"   (real zero, not "OI NA")
  2. contracts empty signature  -> "OI NA"  (open_interest=null + oi_source="missing")
     the HARDZERO data branch that PRODUCES oi_source="missing" is covered by
     test_oi_contracts_join.py (join_contract_open_interest null+missing).

This is a render-CONTRACT smoke test (Python replica of the JS branch, source-cited),
not a live-acceptance. No node required.
"""
from __future__ import annotations

import unittest
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "grid-sovereign-runtime" / "gateway" / "static" / "aether_trading_v12.html"


def _oi_bit(item: dict) -> str:
    """Python replica of the HTML JS branch (aether_trading_v12.html ~566-567)."""
    if item.get("open_interest") is not None:
        return f"OI {item['open_interest']}"
    if item.get("oi_unverified") or item.get("oi_source") == "missing":
        return "OI NA"
    return ""


class RenderOiContractTests(unittest.TestCase):
    def test_html_render_branch_present(self) -> None:
        """Lock the exact render branch in the HTML so it can't drift."""
        src = HTML.read_text(encoding="utf-8")
        self.assertIn('if(item.open_interest!=null) bits.push(`OI ${item.open_interest}`)', src)
        self.assertIn('else if(item.oi_unverified||item.oi_source==="missing") bits.push("OI NA")', src)

    def test_real_zero_renders_oi_0_not_na(self) -> None:
        self.assertEqual(_oi_bit({"open_interest": 0}), "OI 0")

    def test_contracts_empty_renders_oi_na(self) -> None:
        self.assertEqual(_oi_bit({"open_interest": None, "oi_source": "missing"}), "OI NA")

    def test_oi_unverified_also_renders_oi_na(self) -> None:
        self.assertEqual(_oi_bit({"open_interest": None, "oi_unverified": True}), "OI NA")

    def test_real_oi_renders_value(self) -> None:
        self.assertEqual(_oi_bit({"open_interest": 5320}), "OI 5320")


if __name__ == "__main__":
    unittest.main()
