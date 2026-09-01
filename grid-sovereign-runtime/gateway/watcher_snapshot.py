"""Read-only :8520 watcher state for changyu app (via :8501, phone-safe)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import APIRouter

_DEFAULT_STATE = (
    Path(__file__).resolve().parents[2] / "aether_watcher" / "state"
)


def _state_dir() -> Path:
    raw = os.getenv("WATCHER_STATE_DIR", "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_STATE


def _read_json(path: Path, default):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/watcher/snapshot")
    def watcher_snapshot():
        state_dir = _state_dir()
        hb = _read_json(state_dir / "heartbeat.json", {})
        events = _read_json(state_dir / "events.json", [])
        if not isinstance(events, list):
            events = []
        ts = float(hb.get("ts") or 0)
        age = (time.time() - ts) if ts else None
        return {
            "state_dir": str(state_dir),
            "heartbeat": hb,
            "heartbeat_age_sec": int(age) if age is not None else None,
            "online": age is not None and age < 120,
            "targets": hb.get("targets") or [],
            "events": events[-40:],
            "event_count": len(events),
        }

    return router
