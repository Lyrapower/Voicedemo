#!/usr/bin/env python3
"""Premarket Grid compile node — 06:45 EST, report-only, A/B lane (isolated from Sonnet)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from aether_shared import EST, atomic_write_json  # noqa: E402
from aether_grid_emit import emit_premarket_grid  # noqa: E402
from grid_compile_client import compile_premarket  # noqa: E402
from grid_compile_hygiene import parse_premarket_items  # noqa: E402
from premarket_ab_divergence import maybe_push_after_grid  # noqa: E402
from premarket_ab_isolation import assert_grid_prompt_isolated  # noqa: E402
from premarket_ab_journal import append_premarket_journal  # noqa: E402
from premarket_pool_context import build_pool_premarket_context, filter_items_to_pool  # noqa: E402
from daemon_schedule import parse_hhmm, slot_due  # noqa: E402

try:
    from aether_dryrun import is_trading_day
except Exception:
    def is_trading_day(d: dt.date | None = None) -> bool:
        d = d or dt.datetime.now(EST).date()
        return d.weekday() < 5

logger = logging.getLogger("PremarketCompile")
PREMARKET_TIME = os.getenv("PREMARKET_COMPILE_TIME", "06:45")
STATE_PATH = BASE_DIR / "premarket_compile_state.json"
STATE_TEST_DIR = BASE_DIR / "state_test"
_test_mode = False


def set_test_mode(enabled: bool) -> None:
    global _test_mode
    _test_mode = bool(enabled)


def _state_path() -> Path:
    if _test_mode:
        return STATE_TEST_DIR / "premarket_compile_state.json"
    return STATE_PATH


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def build_premarket_context(trade_date: dt.date) -> str:
    """Pool-universe context — Grid lane; must not include Sonnet output."""
    return build_pool_premarket_context(trade_date)


def _store_has_premarket_grid(trade_date: str) -> bool:
    from store_query import store_query_one

    row = store_query_one(
        "SELECT 1 FROM events WHERE source='aether' AND kind='aether_premarket_grid' "
        "AND json_extract(payload, '$.date')=? LIMIT 1",
        (trade_date,),
    )
    return row is not None


def _mark_grid_success(state: dict[str, Any], dkey: str) -> None:
    ts_now = dt.datetime.now(dt.timezone.utc).isoformat()
    completed = state.setdefault("completed_dates", [])
    if dkey not in completed:
        completed.append(dkey)
    state["last_success_ts"] = ts_now
    state["last_success_date"] = dkey
    state.pop("last_failure_ts", None)
    state.pop("last_failure_reason", None)
    atomic_write_json(str(_state_path()), state)


def reparse_latest_from_store(trade_date: dt.date, *, chain: str = "grid") -> dict[str, Any]:
    """Re-parse stored raw without another compile call."""
    import urllib.error
    import urllib.request

    dkey = trade_date.isoformat()
    kind = "aether_premarket_grid" if chain == "grid" else "aether_premarket_sonnet"
    url = os.getenv("GRID_EVENTS", "http://127.0.0.1:8501/store/events").rsplit("/", 1)[0]
    url = f"{url}/events/recent?source=aether&kinds={kind},aether_premarket&per_kind=15"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            events = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        return {"error": str(exc), "trade_date": dkey}

    raw = ""
    for ev in events:
        p = ev.get("payload") or {}
        if ev.get("kind") == kind and p.get("date") == dkey and p.get("raw"):
            raw = p["raw"]
            break
    if not raw:
        for ev in events:
            p = ev.get("payload") or {}
            if p.get("date") == dkey and p.get("raw"):
                raw = p["raw"]
                break
    if not raw:
        return {"error": "no premarket raw in store", "trade_date": dkey, "chain": chain}

    items = filter_items_to_pool(parse_premarket_items(raw) or [])
    result: dict[str, Any] = {"trade_date": dkey, "items": items, "reparse": True, "chain": chain}
    if items:
        emit_premarket_grid(trade_date=dkey, items=items, raw=raw)
        append_premarket_journal(chain="grid", trade_date=dkey, items=items)
        if not _test_mode:
            _mark_grid_success(_read_json(_state_path(), {"completed_dates": []}), dkey)
        logger.info("premarket grid reparse emitted %d items for %s", len(items), dkey)
    else:
        logger.warning("premarket grid reparse produced no items for %s", dkey)
    return result


def run_for_date(trade_date: dt.date, *, force: bool = False) -> dict[str, Any]:
    state = _read_json(_state_path(), {"completed_dates": []})
    dkey = trade_date.isoformat()
    if not force and dkey in (state.get("completed_dates") or []):
        if _store_has_premarket_grid(dkey):
            logger.info("premarket grid compile already done for %s", dkey)
            return {"skipped": True, "trade_date": dkey}
        logger.warning(
            "premarket grid marked complete for %s but store missing aether_premarket_grid — backfill reparse",
            dkey,
        )
        return reparse_latest_from_store(trade_date)

    user_prompt = build_premarket_context(trade_date)
    from tactical_memo import build_memo_prompt_tail

    user_prompt += build_memo_prompt_tail("grid", trade_date.isoformat())
    assert_grid_prompt_isolated(user_prompt)
    items, raw, meta = compile_premarket(user_prompt)
    if items:
        items = filter_items_to_pool(items)
    result: dict[str, Any] = {
        "trade_date": dkey,
        "generated_at": dt.datetime.now(EST).isoformat(),
        "items": items,
        "raw_excerpt": (raw or "")[:2000],
        "meta": meta,
        "chain": "grid",
        "test_mode": _test_mode,
    }
    push_meta: dict[str, Any] = {}
    if items:
        emit_ok = emit_premarket_grid(
            trade_date=dkey,
            items=items,
            raw=raw,
            generated_at=result["generated_at"],
        )
        result["store_emitted"] = emit_ok
        append_premarket_journal(chain="grid", trade_date=dkey, items=items, meta=meta)
        logger.info("premarket grid compile emitted %d items store=%s", len(items), emit_ok)
        if not _test_mode and emit_ok:
            push_meta = maybe_push_after_grid(dkey, items)
            _mark_grid_success(state, dkey)
        elif not _test_mode and not emit_ok:
            # Gate completion on emit: store write failed → do NOT mark success,
            # record failure so the next tick retries instead of silently dropping.
            ts_now = dt.datetime.now(EST).isoformat()
            state["last_failure_ts"] = ts_now
            state["last_failure_date"] = dkey
            state["last_failure_reason"] = "store_emit_failed"
            logger.error("premarket grid compile store emit FAILED — not marking success (will retry)")
    else:
        err = meta.get("error") or ("field_drift" if raw else "empty_parse")
        logger.warning(
            "premarket grid compile produced no store items (drift or parse empty) err=%s",
            err,
        )
        if not _test_mode:
            ts_now = dt.datetime.now(EST).isoformat()
            state["last_failure_ts"] = ts_now
            state["last_failure_date"] = dkey
            state["last_failure_reason"] = err
            failed = state.setdefault("failed_dates", [])
            if dkey not in failed:
                failed.append(dkey)
            atomic_write_json(str(_state_path()), state)
    result["divergence_push"] = push_meta
    return result


def scheduler_loop() -> None:
    hour, minute = parse_hhmm(PREMARKET_TIME)
    logger.info("premarket grid compile daemon | fire at %02d:%02d EST", hour, minute)
    while True:
        now = dt.datetime.now(EST)
        if now.weekday() < 5 and is_trading_day(now.date()):
            dkey = now.date().isoformat()
            state = _read_json(_state_path(), {"completed_dates": []})
            pending = dkey not in (state.get("completed_dates") or []) or not _store_has_premarket_grid(dkey)
            if pending and slot_due(now, hour, minute):
                try:
                    run_for_date(now.date(), force=False)
                except Exception:
                    logger.exception("premarket grid compile failed for %s", dkey)
                time.sleep(65)
        time.sleep(20)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    ap = argparse.ArgumentParser(description="Aether premarket Grid compile (report-only, A/B lane)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--reparse", action="store_true", help="Re-parse latest store raw and re-emit (no Grid call)")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--test", action="store_true", help="No production state writes")
    args = ap.parse_args()
    set_test_mode(bool(args.test or os.getenv("AETHER_TEST", "").lower() in ("1", "true", "yes")))
    if _test_mode:
        STATE_TEST_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("TEST MODE: state -> %s", STATE_TEST_DIR)

    trade_date = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(EST).date()
    if args.reparse:
        print(json.dumps(reparse_latest_from_store(trade_date), ensure_ascii=False, indent=2))
        return
    if args.loop and not args.once:
        scheduler_loop()
        return
    out = run_for_date(trade_date, force=args.force)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
