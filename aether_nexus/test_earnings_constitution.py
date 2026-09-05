"""E-3 earnings direction assert + confabulation gate."""
from __future__ import annotations

from earnings_confabulation import validate_earnings_item


def test_bearish_earnings_item_dropped():
    ok, hits = validate_earnings_item(
        prompt="交易日：2026-07-15\n- NVDA 财报 2026-07-16",
        item={"sym": "NVDA", "value": "空 · [观察]", "note": "why", "dir": -1},
    )
    assert not ok
    assert any("bearish" in h for h in hits)


def test_long_earnings_item_passes_when_grounded():
    ok, hits = validate_earnings_item(
        prompt="交易日：2026-07-15\n- NVDA 财报 2026-07-16",
        item={"sym": "NVDA", "value": "多 · [试探性]", "note": "过滤器读数齐全", "dir": 1},
    )
    assert ok
    assert hits == []
