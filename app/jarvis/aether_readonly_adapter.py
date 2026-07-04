"""Read-only Aether Nexus adapter — signals and validation only; no IB execution."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
AETHER_DIR = ROOT / "aether_nexus"
SNAPSHOT_OUT = ROOT / "deliver" / "proof" / "jarvis" / "aether_snapshot_latest.json"


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _latest_signal_meta(signals: list[Any] | None) -> dict[str, Any]:
    if not signals or not isinstance(signals, list):
        return {"count": 0, "latest_scan_time": None, "top_symbols": []}
    latest = signals[-1] if signals else {}
    if not isinstance(latest, dict):
        return {"count": len(signals), "latest_scan_time": None, "top_symbols": []}
    cands = latest.get("candidates") or []
    symbols: list[str] = []
    for c in cands[:5]:
        if isinstance(c, dict) and c.get("symbol"):
            symbols.append(str(c["symbol"]))
    return {
        "count": len(signals),
        "latest_scan_time": latest.get("scan_time"),
        "candidate_count": len(cands) if isinstance(cands, list) else 0,
        "top_symbols": symbols,
        "top_pick": latest.get("top_pick"),
    }


def load_aether_snapshot(*, write_artifact: bool = True) -> dict[str, Any]:
    """Load Aether state files read-only. Never writes commands/ or triggers trades."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not AETHER_DIR.is_dir():
        snap = {
            "available": False,
            "read_only": True,
            "execution_blocked": True,
            "ts": now,
            "reason": "aether_nexus directory missing",
            "paths_checked": [str(AETHER_DIR)],
        }
        if write_artifact:
            _write_snapshot_artifact(snap)
        return snap

    status = _read_json(AETHER_DIR / "state" / "status.json")
    candidates = _read_json(AETHER_DIR / "state" / "candidates.json")
    signals = _read_json(AETHER_DIR / "dryrun_state" / "signals.json")
    pool_signals = _read_json(AETHER_DIR / "dryrun_state" / "pool_signals.json")
    data_health = _read_json(AETHER_DIR / "dryrun_state" / "data_health.json")

    cand_rows = []
    cand_symbols: list[str] = []
    if isinstance(candidates, dict):
        cand_rows = candidates.get("rows") or []
        cand_symbols = candidates.get("symbols") or []
        if not isinstance(cand_rows, list):
            cand_rows = []
        if not isinstance(cand_symbols, list):
            cand_symbols = []

    snap: dict[str, Any] = {
        "available": True,
        "read_only": True,
        "execution_blocked": True,
        "ib_auto_execution": False,
        "commands_dir_write": False,
        "ts": now,
        "aether_version_hint": "R5.4.1",
        "status": status if isinstance(status, dict) else {},
        "candidates": {
            "scan_timestamp": (candidates or {}).get("scan_timestamp") if isinstance(candidates, dict) else None,
            "source": (candidates or {}).get("source") if isinstance(candidates, dict) else None,
            "row_count": len(cand_rows),
            "symbols": cand_symbols[:20],
        },
        "dryrun_signals": _latest_signal_meta(signals if isinstance(signals, list) else None),
        "pool_signals_meta": _latest_signal_meta(pool_signals if isinstance(pool_signals, list) else None),
        "data_health": data_health if isinstance(data_health, dict) else {},
        "validation": {
            "daemon_connected": bool((status or {}).get("connected")) if isinstance(status, dict) else False,
            "live_trading_enabled": bool((status or {}).get("live_trading_enabled")) if isinstance(status, dict) else False,
            "jarvis_merged_execution": False,
            "policy": "signal_only — manual execution on Jarvis; no IB orders from platform_main",
        },
        "sidecar_note": "Aether daemon/dashboard remain sidecar processes (:8510). Jarvis reads JSON only.",
    }
    if write_artifact:
        _write_snapshot_artifact(snap)
    return snap


def _write_snapshot_artifact(snap: dict[str, Any]) -> None:
    SNAPSHOT_OUT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_OUT.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
