#!/usr/bin/env python3
"""Crypto paper CC CLI lane — sonnet-4.6 signals → crypto_cli inbox (A/B vs rules).

Isolated from: aether_offpool, equity scan, crypto_rules inbox, IB daemon.
CC_CLI_EXECUTION_FROZEN=1 — claude -p only; paper engine executes locally.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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
from paper.cc_cli import (  # noqa: E402
    build_crypto_cli_prompt,
    claude_capture,
    default_crypto_cli_lane,
    parse_crypto_cli_items,
)
from paper import crypto_feed  # noqa: E402
from paper.emit import emit_crypto_paper_ab  # noqa: E402
from paper.store import append_jsonl, atomic_write_json, init_crypto_lane, is_lane_initialized, lane_paths, load_processed  # noqa: E402
from paper.summary import crypto_ab_payload  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("paper_crypto_cli")

from zoneinfo import ZoneInfo  # noqa: E402
EST = ZoneInfo("America/New_York")  # DST-aware, replaces fixed UTC-5
STATE_PATH = BASE / "state" / "crypto_cli_daily_state.json"
TRACE_DIR = REPO_ROOT / "grid-sovereign-runtime" / "traces" / "paper_crypto_ab"


def _day_key(d: dt.date | None = None) -> str:
    d = d or dt.datetime.now(EST).date()
    return d.isoformat()


def signal_key(day: str, symbol: str) -> str:
    return hashlib.sha256(f"{day}|{symbol}|crypto_cli".encode()).hexdigest()[:16]


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
    day = trade_date or _day_key()
    state = _load_state()
    completed = state.setdefault("completed", {})
    if completed.get(day) and not force:
        logger.info("crypto cli already ran for %s", day)
        return {"skipped": True, "day": day}

    if not is_lane_initialized("crypto_cli"):
        init_crypto_lane(
            lane="crypto_cli",
            days=int(os.getenv("PAPER_EXPERIMENT_DAYS", "30")),
        )
        logger.info("crypto_cli ledger initialized (explicit 09:10 init, not paper_daemon)")

    lane = default_crypto_cli_lane()
    marks = crypto_feed.marks(["BTC-USD", "ETH-USD", "SOL-USD"], prefer="coinbase")
    prompt = build_crypto_cli_prompt(trade_date=day, marks=marks)
    raw, meta = claude_capture(prompt, lane)
    items = parse_crypto_cli_items(raw or "")

    paths = lane_paths("crypto_cli")
    processed = load_processed(lane="crypto_cli")
    enqueued = 0
    for item in items:
        sym = item["sym"]
        key = signal_key(day, sym)
        if key in processed:
            continue
        sig = {
            "symbol": sym,
            "want_pct": item["want_pct"],
            "scan_time": f"{day}T09:10:00Z",
            "scan_mode": "crypto_cli",
            "label": lane.lane,
            "reason": f"crypto_cli:{lane.lane}:{item.get('note', '')[:60]}",
            "ref_price": marks.get(sym),
            "key": key,
        }
        append_jsonl(paths["inbox"], sig)
        enqueued += 1

    result = {
        "trade_date": day,
        "lane": lane.lane,
        "cli_model": lane.cli_model,
        "items": items,
        "enqueued": enqueued,
        "meta": meta,
        "raw_excerpt": (raw or "")[:2000],
        "broker_execution": False,
    }
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(TRACE_DIR / f"crypto_cli_{day}.json", result)
    completed[day] = True
    _save_state(state)

    ab = crypto_ab_payload()
    ab["cli_capture"] = {
        "items": len(items),
        "enqueued": enqueued,
        "cost_usd": meta.get("cost_usd"),
        "error": meta.get("error"),
    }
    emit_crypto_paper_ab(ab)
    logger.info(
        "crypto cli day=%s items=%d enqueued=%d error=%s",
        day,
        len(items),
        enqueued,
        meta.get("error"),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--time", default=os.getenv("CRYPTO_PAPER_CLI_TIME", "09:10"))
    args = parser.parse_args()

    if args.once or not args.loop:
        run(force=args.force)
        return

    target_h, target_m = parse_hhmm(args.time)
    logger.info("crypto cli loop waiting for %02d:%02d EST", target_h, target_m)
    while True:
        now = dt.datetime.now(EST)
        if now.weekday() < 5 and slot_due(now, target_h, target_m):
            run()
            time.sleep(70)
        time.sleep(30)


if __name__ == "__main__":
    main()
