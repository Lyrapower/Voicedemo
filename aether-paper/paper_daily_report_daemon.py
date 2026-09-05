#!/usr/bin/env python3
"""Paper 日报 —— 16:40 emit aether_paper_daily + crypto A/B snapshot.

Read-only aggregate; never writes trades or merges ledgers.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO_ROOT = BASE.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(REPO_ROOT / "aether_nexus"))

from daemon_schedule import parse_hhmm, slot_due  # noqa: E402
from paper.emit import emit_crypto_paper_ab, emit_paper_daily  # noqa: E402
from paper.store import atomic_write_json  # noqa: E402
from paper.summary import crypto_ab_payload, daily_report_payload  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("paper_daily_report")

from zoneinfo import ZoneInfo  # noqa: E402
EST = ZoneInfo("America/New_York")  # DST-aware, replaces fixed UTC-5
STATE_PATH = BASE / "state" / "paper_daily_state.json"
TRACE_DIR = REPO_ROOT / "grid-sovereign-runtime" / "traces" / "paper_daily"
REPORT_TIME = os.getenv("PAPER_DAILY_TIME", "16:40")


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"completed": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"completed": {}}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(STATE_PATH, state)


def run(*, force: bool = False, trade_date: str | None = None) -> dict:
    day = trade_date or dt.datetime.now(EST).date().isoformat()
    state = _load_state()
    completed = state.setdefault("completed", {})
    if completed.get(day) and not force:
        logger.info("paper daily already emitted for %s", day)
        return {"skipped": True, "day": day}

    payload = daily_report_payload(day)
    ab = crypto_ab_payload()
    ok_daily = emit_paper_daily(payload)
    ok_ab = emit_crypto_paper_ab(ab)
    result = {
        "trade_date": day,
        "emit_daily": ok_daily,
        "emit_ab": ok_ab,
        "payload": payload,
    }
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(TRACE_DIR / f"paper_daily_{day}.json", result)
    completed[day] = True
    _save_state(state)
    logger.info("paper daily %s emit_daily=%s emit_ab=%s", day, ok_daily, ok_ab)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.once or not args.loop:
        run(force=args.force)
        return

    target_h, target_m = parse_hhmm(REPORT_TIME)
    logger.info("paper daily loop @ %02d:%02d local", target_h, target_m)
    while True:
        now = dt.datetime.now()
        if now.weekday() < 5 and slot_due(now, target_h, target_m):
            run()
            time.sleep(70)
        time.sleep(30)


if __name__ == "__main__":
    main()
