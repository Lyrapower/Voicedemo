"""Off-pool prompt whitelist + emit filter tests."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import importlib.util

spec = importlib.util.spec_from_file_location("offpool", ROOT / "aether_offpool_daemon.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["offpool"] = mod
spec.loader.exec_module(mod)

from offpool_ab_stats import (  # noqa: E402
    grounded_emit_items,
    load_offpool_candidates,
    near_miss_symbols_from_rejection_log,
    store_stats_from_emit,
)
import offpool_ab_stats as stats  # noqa: E402

LEAK_MARKER = "OFFPOOL_LEAK_PROBE_ZQ7K9M"
TRADE_DATE = dt.date(2026, 7, 10)


def test_prompt_excludes_dryrun_tail_marker(tmp_path, monkeypatch):
    dryrun = tmp_path / "dryrun_state"
    dryrun.mkdir()
    log = dryrun / "dryrun.log"
    log.write_text(f"normal line\nINJECTED {LEAK_MARKER} must not appear\n", encoding="utf-8")
    perilla = dryrun / "perilla_signals.json"
    perilla.write_text(json.dumps({"buy_signals": [{"symbol": "NVDA", "score": 99}]}), encoding="utf-8")

    rej_dir = tmp_path / "logs" / "rejections"
    rej_dir.mkdir(parents=True)
    (rej_dir / "scan.jsonl").write_text(
        json.dumps({"symbol": "MKSI", "score": 39.6, "kill_rule": "spread"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "DRYRUN_STATE", dryrun)
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    monkeypatch.setattr(stats, "_SP500_CACHE", {"MKSI"})

    prompt = mod.build_offpool_context(TRADE_DATE)
    assert LEAK_MARKER not in prompt
    assert "dryrun tail" not in prompt.lower()
    assert "perilla" not in prompt.lower()
    assert "MKSI" in prompt
    assert "whitelist" in prompt.lower()


def test_near_miss_full_file_includes_late_symbol(tmp_path):
    rej = tmp_path / "rej.jsonl"
    lines = [json.dumps({"symbol": "AMKR", "score": 40.0, "kill_rule": "x"})]
    lines += [json.dumps({"symbol": "PAD", "score": 1.0, "kill_rule": "y"})] * 500
    lines.append(json.dumps({"symbol": "CRWD", "score": 34.9, "kill_rule": "spread"}))
    rej.write_text("\n".join(lines) + "\n", encoding="utf-8")

    syms = near_miss_symbols_from_rejection_log(rej, pool_syms={"POOL"})
    assert "CRWD" in syms
    assert len(syms) == 3

    cands = load_offpool_candidates(rej, pool_syms={"POOL"}, sp500_only=False)
    assert any(c["sym"] == "CRWD" for c in cands)


def test_offpool_candidates_exclude_non_sp500(monkeypatch, tmp_path):
    rej = tmp_path / "rej.jsonl"
    rej.write_text(
        "\n".join(
            [
                json.dumps({"symbol": "CRWD", "score": 34.9, "kill_rule": "spread"}),
                json.dumps({"symbol": "ONTO", "score": 39.0, "kill_rule": "spread"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(stats, "_SP500_CACHE", {"CRWD"})
    assert [c["sym"] for c in load_offpool_candidates(rej, pool_syms=set())] == ["CRWD"]


def test_empty_sp500_universe_does_not_wipe_whitelist(monkeypatch, tmp_path):
    """S&P load failure (empty set) must not silently drop all near-miss candidates."""
    rej = tmp_path / "rej.jsonl"
    rej.write_text(
        json.dumps({"symbol": "CRWD", "score": 34.9, "kill_rule": "spread"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(stats, "_SP500_CACHE", set())
    assert [c["sym"] for c in load_offpool_candidates(rej, pool_syms=set())] == ["CRWD"]


def test_grounded_emit_drops_fabricated():
    raw = [
        {"sym": "MKSI", "value": "观察", "note": "ok", "dir": 0},
        {"sym": "CRWD", "value": "多", "note": "bad", "dir": 1},
    ]
    emit, dropped = grounded_emit_items(raw, near_miss_syms={"MKSI", "CRWD"}, pool_syms=set())
    assert len(emit) == 2
    emit2, dropped2 = grounded_emit_items(raw, near_miss_syms={"MKSI"}, pool_syms=set())
    assert len(emit2) == 1
    assert emit2[0]["sym"] == "MKSI"
    assert "CRWD" in dropped2


def test_store_stats_omit_fabrication_labels():
    stats = store_stats_from_emit([{"sym": "MKSI"}], near_miss_count=11, parse_ok=True)
    assert "fabricated_count" not in stats
    assert "hard_pad" not in stats
    assert stats["item_count"] == 1


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-q"])
