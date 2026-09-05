#!/usr/bin/env python3
"""M1 — listen for self-reported failures in daily briefs; alert on ≥2 consecutive days."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from aether_shared import EST, atomic_write_json, send_notification  # noqa: E402

logger = logging.getLogger("BriefSelfReportListener")
STATE_PATH = BASE_DIR / "state" / "brief_listener_state.json"
GRID_EVENTS = os.getenv("GRID_EVENTS", "http://127.0.0.1:8501/store/events").rsplit("/", 1)[0]

FAIL_PATTERNS = re.compile(
    r"失败|错误|受损|无效|数据链路|SSL|宇宙为空|integrity_fail|catalyst",
    re.I,
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def fetch_recent_briefs(limit: int = 10) -> list[dict[str, Any]]:
    url = f"{GRID_EVENTS}/events/recent?source=aether&kinds=aether_brief&per_kind={limit}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("brief fetch failed: %s", exc)
        return []


def brief_has_failure(payload: dict[str, Any]) -> bool:
    body = str(payload.get("body") or "")
    title = str(payload.get("title") or "")
    blob = f"{title}\n{body}"
    if FAIL_PATTERNS.search(blob):
        return True
    for it in payload.get("items") or []:
        if FAIL_PATTERNS.search(str(it.get("value") or "") + str(it.get("note") or "")):
            return True
    return False


def run_once(*, alert_threshold: int = 2) -> dict[str, Any]:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = _read_json(STATE_PATH, {"streak": 0, "last_dates": [], "alerts": []})
    events = fetch_recent_briefs(limit=5)
    today = dt.datetime.now(EST).date().isoformat()
    checked_dates: list[str] = []
    streak = 0
    for ev in sorted(events, key=lambda e: (e.get("payload") or {}).get("date") or ""):
        p = ev.get("payload") or {}
        d = p.get("date")
        if not d or d in checked_dates:
            continue
        checked_dates.append(d)
        if brief_has_failure(p):
            streak += 1
        else:
            break
    state["streak"] = streak
    state["last_checked"] = dt.datetime.now(dt.timezone.utc).isoformat()
    state["last_dates"] = checked_dates[:5]
    alerted = False
    if streak >= alert_threshold:
        msg = f"⚠️ Aether 日报自省 · 连续 {streak} 日自报链路/数据故障 · 最近 {checked_dates[:3]}"
        send_notification(msg)
        alerts = state.setdefault("alerts", [])
        alerts.append({"ts": state["last_checked"], "streak": streak, "dates": checked_dates[:3]})
        state["alerts"] = alerts[-20:]
        alerted = True
        logger.warning("brief self-report alert streak=%d", streak)
    atomic_write_json(str(STATE_PATH), state)
    return {"streak": streak, "dates": checked_dates, "alerted": alerted, "today": today}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    ap = argparse.ArgumentParser(description="Brief self-report listener (M1)")
    ap.add_argument("--once", action="store_true", default=True)
    ap.add_argument("--threshold", type=int, default=2)
    args = ap.parse_args()
    out = run_once(alert_threshold=args.threshold)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
