"""Scan-round quarantine (mirror aether_nexus/scan_quarantine.json)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).resolve().parent / "scan_quarantine.json"


def _load() -> list[dict[str, Any]]:
    if not _CONFIG_PATH.is_file():
        return []
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    rounds = data.get("rounds")
    return rounds if isinstance(rounds, list) else []


def is_quarantined(
    *,
    event_id: int | None = None,
    date: str | None = None,
    window: str | None = None,
) -> bool:
    w = (window or "").upper()
    for rnd in _load():
        ids = rnd.get("scan_event_ids") or []
        if event_id is not None and event_id in ids:
            return True
        if date and w and rnd.get("date") == date and str(rnd.get("window", "")).upper() == w:
            return True
    return False


def status_payload() -> dict[str, Any]:
    rounds = _load()
    active = bool(rounds)
    ids: list[int] = []
    for rnd in rounds:
        ids.extend(int(x) for x in (rnd.get("scan_event_ids") or []))
    return {
        "active": active,
        "scan_event_ids": sorted(set(ids)),
        "rounds": rounds,
        "banner": "本轮查证中 · 不作数" if active else "",
    }
