"""fact_pack reads logs/rejections (same as aether_dryrun writer)."""
from __future__ import annotations

import json
from pathlib import Path

from postmarket_fact_pack import FILTER_DIR, _filter_counts, _rejection_log_dirs


def test_rejection_dirs_prefers_logs_rejections(tmp_path, monkeypatch):
    base = tmp_path / "nx"
    rej = base / "logs" / "rejections"
    rej.mkdir(parents=True)
    fp = rej / "2026-07-27_test.jsonl"
    fp.write_text(
        json.dumps({"kill_rule": "spread", "symbol": "AAPL"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("postmarket_fact_pack.BASE", base)
    monkeypatch.setattr("postmarket_fact_pack.FILTER_DIR", base / "logs" / "rejections")
    monkeypatch.setattr("postmarket_fact_pack.FILTER_DIR_LEGACY", base / "dryrun_state" / "rejection_logs")
    assert base / "logs" / "rejections" in _rejection_log_dirs()
    counts = _filter_counts("2026-07-27")
    assert counts.get("spread") == 1


def test_filter_dir_points_at_logs_rejections():
    assert FILTER_DIR.name == "rejections"
    assert "logs" in str(FILTER_DIR)
