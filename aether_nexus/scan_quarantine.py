"""Scan-round quarantine — downstream consumers skip quarantined BFS rounds."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent / "scan_quarantine.json"


def _load() -> list[dict[str, Any]]:
    if not _CONFIG_PATH.is_file():
        return []
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("scan_quarantine config unreadable: %s", exc)
        return []
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


def skip_log(event_id: int | None, *, consumer: str, date: str = "", window: str = "") -> None:
    log.info(
        "scan_quarantine skip consumer=%s event_id=%s date=%s window=%s reason=quarantine",
        consumer,
        event_id,
        date,
        window,
    )
