#!/usr/bin/env python3
"""Unit tests — deepseek_performance_summary."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import deepseek_performance_summary as dps  # noqa: E402


def _write_trace(name: str, payload: dict) -> None:
    dps.TRACE_DIR.mkdir(parents=True, exist_ok=True)
    (dps.TRACE_DIR / name).write_text(json.dumps(payload), encoding="utf-8")


def test_build_and_format_with_traces(tmp_path, monkeypatch):
    monkeypatch.setattr(dps, "TRACE_DIR", tmp_path)
    d = dt.date(2026, 7, 23)
    dkey = d.isoformat()
    _write_trace(
        f"offpool_sonnet-4.6_{dkey}.json",
        {
            "trade_date": dkey,
            "lane": "sonnet-4.6",
            "items": [{"sym": "AAPL"}, {"sym": "MSFT"}],
            "stats": {"item_count": 2, "duration_ms": 17000, "cost_usd": 0.067, "parse_ok": True, "in_pool_count": 0},
            "audit": {"fabricated_count": 1, "fabrication_rate": 0.5, "hard_pad": True},
        },
    )
    _write_trace(
        f"offpool_deepseek-v4_{dkey}.json",
        {
            "trade_date": dkey,
            "lane": "deepseek-v4",
            "items": [{"sym": "AAPL"}, {"sym": "NVDA"}],
            "stats": {"item_count": 2, "duration_ms": 7400, "parse_ok": True, "in_pool_count": 0},
            "audit": {"fabricated_count": 0, "fabrication_rate": 0.0, "hard_pad": False},
        },
    )
    _write_trace(
        f"premarket_deepseek_premarket_{dkey}.json",
        {
            "trade_date": dkey,
            "window": "premarket",
            "window_label": "06:40 premarket",
            "items": [{"sym": "AAPL"}] * 5,
            "meta": {"duration_ms": 11200},
        },
    )
    monkeypatch.setattr(
        dps,
        "fetch_premarket_from_store",
        lambda *, kind, trade_date: [],
    )
    summary = dps.build_deepseek_performance_summary(dkey)
    assert summary["offpool"]["daily"]["deepseek-v4"]["item_count"] == 2
    assert summary["offpool"]["comparison"]["faster_lane"] == "deepseek"
    assert summary["offpool"]["comparison"]["cleaner_lane"] == "deepseek"
    text = dps.format_deepseek_performance_text(summary)
    assert "DeepSeek 表现" in text
    assert "Off-pool" in text
    assert "盘前 DeepSeek" in text
    items = dps.deepseek_performance_brief_items(summary)
    assert any(i.get("label") == "ds_offpool" for i in items)
    assert any(i.get("label") == "ds_premarket" for i in items)


def test_empty_returns_blank(monkeypatch):
    monkeypatch.setattr(
        dps,
        "fetch_premarket_from_store",
        lambda *, kind, trade_date: [],
    )
    summary = dps.build_deepseek_performance_summary("2099-01-01")
    assert dps.format_deepseek_performance_text(summary) == ""
    assert dps.deepseek_performance_brief_items(summary) == []
