"""Fable off-pool coach trial daemon — isolated from legacy offpool + 30d A/B."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import pytz

NEXUS_DIR = Path(__file__).resolve().parent
if str(NEXUS_DIR) not in sys.path:
    sys.path.insert(0, str(NEXUS_DIR))

from aether_grid_emit import emit_offpool_coach  # noqa: E402
from aether_shared import EST, atomic_write_json  # noqa: E402
from daemon_schedule import parse_hhmm, slot_due  # noqa: E402
from offpool_coach import config as cfg  # noqa: E402
from offpool_coach.calendar_gate import is_half_trading_day  # noqa: E402
from offpool_coach.schema import Window  # noqa: E402
from offpool_coach.stage2_payload_builder import build_payload, write_sample  # noqa: E402
from offpool_coach.stage3_fable_call import call_fable, load_system_prompt  # noqa: E402
from offpool_coach.stage4_gate_and_log import gate_response, log_run  # noqa: E402
from offpool_coach.mandatory_pick import ensure_minimum_verdict, pick_count_from_gated  # noqa: E402

logger = logging.getLogger("offpool_coach")

PST = pytz.timezone("US/Pacific")
STATE_PATH = NEXUS_DIR / "offpool_coach_state.json"

try:
    from aether_dryrun import is_trading_day
except Exception:

    def is_trading_day(d: dt.date | None = None) -> bool:
        d = d or dt.datetime.now(EST).date()
        return d.weekday() < 5


def _trial_start() -> dt.date:
    return dt.date.fromisoformat(cfg.TRIAL_START_DATE)


def _before_trial(d: dt.date) -> bool:
    return d < _trial_start()


def _slot_key(trade_date: dt.date, window: Window) -> str:
    return f"{trade_date.isoformat()}:{window}"


def _read_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"trial_start_date": cfg.TRIAL_START_DATE, "completed_slots": {}}


def _write_state(state: dict[str, Any]) -> None:
    atomic_write_json(str(STATE_PATH), state)


def _slot_done(state: dict[str, Any], trade_date: dt.date, window: Window) -> bool:
    return _slot_key(trade_date, window) in (state.get("completed_slots") or {})


def backfill_store_emits(trade_date: dt.date | None = None) -> list[dict[str, Any]]:
    """Re-emit aether_offpool_coach from trace jsonl when Fable ran but store POST failed."""
    from aether_grid_emit import emit_offpool_coach, store_has_aether_event

    trade_date = trade_date or dt.datetime.now(PST).date()
    dkey = trade_date.isoformat()
    trace = Path(cfg.OUTPUT_DIR) / f"{dkey}.jsonl"
    if not trace.is_file():
        return []
    actions: list[dict[str, Any]] = []
    for line in trace.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("kind") != "coach_run" or not row.get("gated_ok"):
            continue
        window = str(row.get("window") or "")
        if not window:
            continue
        if store_has_aether_event("aether_offpool_coach", trade_date=dkey, window=window):
            continue
        raw = str(row.get("raw_excerpt") or "")
        if not raw.strip():
            actions.append({"window": window, "ok": False, "reason": "no_raw"})
            continue
        try:
            start = raw.index("[") if "[" in raw else raw.index("{")
            end = raw.rindex("]") + 1 if "[" in raw else raw.rindex("}") + 1
            picks = json.loads(raw[start:end])
        except (ValueError, json.JSONDecodeError) as exc:
            actions.append({"window": window, "ok": False, "reason": f"parse:{exc}"})
            continue
        if not isinstance(picks, list):
            picks = [picks]
        ok = emit_offpool_coach(
            trade_date=dkey,
            window=window,
            picks=picks,
            pick_count=int(row.get("pick_count") or len(picks)),
            verdict_source=str(row.get("verdict_source") or "fable"),
            gated_ok=True,
        )
        actions.append({"window": window, "ok": ok, "reason": "backfill"})
        if ok:
            logger.info("offpool coach store backfill ok %s %s", window, dkey)
        else:
            logger.warning("offpool coach store backfill failed %s %s", window, dkey)
    return actions


def run_once(
    *,
    window: Window = "PREMARKET",
    trade_date: dt.date | None = None,
    skip_fable: bool = False,
    staleness_anchor: str = "now",
) -> dict[str, Any]:
    trade_date = trade_date or dt.datetime.now(PST).date()
    cfg.refresh_risk_budget(trade_date=trade_date)
    logger.info(
        "coach %s risk_budget usd=%s equity=%s as_of=%s",
        window,
        cfg.RISK_BUDGET_USD,
        cfg.ACCOUNT_EQUITY_USD,
        cfg.RISK_BUDGET_AS_OF,
    )
    payload = build_payload(window=window, trade_date=trade_date, staleness_anchor=staleness_anchor)  # type: ignore[arg-type]
    dkey = trade_date.isoformat()

    if skip_fable or cfg.RISK_BUDGET_USD is None:
        logger.info(
            "payload-only %s candidates=%d risk_budget=%s",
            window,
            len(payload.get("candidates") or []),
            cfg.RISK_BUDGET_USD,
        )
        out = Path(cfg.OUTPUT_DIR) / f"payload_{window}_{dkey}.json"
        write_sample(out, payload)
        return {
            "trade_date": dkey,
            "window": window,
            "candidates": len(payload.get("candidates") or []),
            "payload_path": str(out),
        }

    raw, meta = call_fable(payload)
    raw, gated, verdict_meta = ensure_minimum_verdict(raw, payload)
    meta = {**(meta or {}), **verdict_meta}
    ph = hashlib.sha256((load_system_prompt() + dkey + window).encode()).hexdigest()[:12]
    pick_count = pick_count_from_gated(gated)
    log_path = log_run(
        payload=payload, prompt_hash=ph, raw_response=raw, gated=gated,
        trade_date=dkey, pick_count=pick_count, verdict_source=meta.get("verdict_source"),
    )
    store_emitted = False
    if pick_count >= cfg.MIN_COACH_PICKS_PER_WINDOW and gated.get("ok"):
        parsed = gated.get("parsed") or []
        store_emitted = emit_offpool_coach(
            trade_date=dkey,
            window=window,
            picks=parsed,
            pick_count=pick_count,
            verdict_source=meta.get("verdict_source"),
            candidates=len(payload.get("candidates") or []),
            gated_ok=bool(gated.get("ok")),
        )
        if store_emitted:
            logger.info("offpool coach emit ok %s %s picks=%d", window, dkey, pick_count)
        else:
            logger.error(
                "offpool coach emit FAILED %s %s picks=%d — store unreachable; slot will NOT be marked complete",
                window,
                dkey,
                pick_count,
            )
    return {
        "trade_date": dkey,
        "window": window,
        "candidates": len(payload.get("candidates") or []),
        "pick_count": pick_count,
        "gated": gated,
        "meta": meta,
        "log_path": str(log_path),
        "store_emitted": store_emitted,
    }


def run_for_date(
    trade_date: dt.date,
    *,
    window: Window = "PREMARKET",
    force: bool = False,
    skip_fable: bool = False,
    staleness_anchor: str = "now",
    track_completion: bool = True,
) -> dict[str, Any]:
    if _before_trial(trade_date):
        logger.info("before trial_start_date=%s — skip %s %s", cfg.TRIAL_START_DATE, trade_date, window)
        return {"skipped": True, "trade_date": trade_date.isoformat(), "window": window, "reason": "before_trial_start"}

    if window == "EXECUTION" and is_half_trading_day(trade_date):
        logger.info("half trading day — EXECUTION skipped per spec §1")
        return {"skipped": True, "trade_date": trade_date.isoformat(), "window": window, "reason": "half_day"}

    state = _read_state()
    dkey = trade_date.isoformat()
    skey = _slot_key(trade_date, window)
    if not force and _slot_done(state, trade_date, window):
        logger.info("offpool coach slot already done: %s", skey)
        return {"skipped": True, "trade_date": dkey, "window": window}

    try:
        result = run_once(
            window=window,
            trade_date=trade_date,
            skip_fable=skip_fable,
            staleness_anchor=staleness_anchor,
        )
    except FileNotFoundError as exc:
        logger.warning("offpool coach deferred — %s", exc)
        return {"skipped": True, "trade_date": dkey, "window": window, "reason": "no_rejection_log", "detail": str(exc)}

    if track_completion and not skip_fable:
        pick_count = int(result.get("pick_count") or 0)
        if pick_count < cfg.MIN_COACH_PICKS_PER_WINDOW:
            logger.error(
                "offpool coach %s %s: pick_count=%d < minimum %d — slot NOT marked complete",
                window, dkey, pick_count, cfg.MIN_COACH_PICKS_PER_WINDOW,
            )
            result["minimum_pick_failed"] = True
            return result
        # Gate completion on emit success: a slot whose store emit failed must stay
        # pending so the next scheduler tick retries it, instead of being marked
        # done and silently missing from the mobile app.
        if not result.get("store_emitted"):
            logger.error(
                "offpool coach %s %s: store emit failed — slot NOT marked complete (will retry)",
                window,
                dkey,
            )
            result["emit_failed"] = True
            return result
        slots = state.setdefault("completed_slots", {})
        gated = result.get("gated") or {}
        slots[skey] = {
            "completed_at": dt.datetime.now(PST).isoformat(),
            "gated_ok": gated.get("ok"),
            "gated_reason": gated.get("reason"),
            "candidates": result.get("candidates"),
            "pick_count": pick_count,
            "verdict_source": (result.get("meta") or {}).get("verdict_source"),
            "log_path": result.get("log_path"),
        }
        state["last_slot"] = slots[skey]
        state["trial_start_date"] = cfg.TRIAL_START_DATE
        _write_state(state)

    return result


def _maybe_run_window(
    now: dt.datetime,
    trade_date: dt.date,
    *,
    window: Window,
    hour: int,
    minute: int,
) -> None:
    state = _read_state()
    if _slot_done(state, trade_date, window):
        return
    if slot_due(now, hour, minute):
        try:
            run_for_date(trade_date, window=window, force=False, staleness_anchor="now", track_completion=True)
        except Exception:
            logger.exception("offpool coach failed %s %s", window, trade_date.isoformat())
        time.sleep(65)


def scheduler_loop() -> None:
    pre_h, pre_m = parse_hhmm(cfg.PREMARKET_WINDOW_PST)
    exe_h, exe_m = parse_hhmm(cfg.EXEC_WINDOW_PST)
    logger.info(
        "offpool coach | spec §1 PST | PREMARKET %02d:%02d | EXECUTION %02d:%02d | trial_start=%s",
        pre_h,
        pre_m,
        exe_h,
        exe_m,
        cfg.TRIAL_START_DATE,
    )
    while True:
        now = dt.datetime.now(PST)
        if now.weekday() >= 5 or not is_trading_day(now.date()):
            time.sleep(20)
            continue
        if _before_trial(now.date()):
            time.sleep(60)
            continue

        d = now.date()
        backfill_store_emits(d)
        _maybe_run_window(now, d, window="PREMARKET", hour=pre_h, minute=pre_m)
        if not is_half_trading_day(d):
            _maybe_run_window(now, d, window="EXECUTION", hour=exe_h, minute=exe_m)
        time.sleep(20)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Offpool coach trial daemon (spec §1 dual window)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true", help="Schedule loop — PREMARKET + EXECUTION PST")
    ap.add_argument("--window", choices=("PREMARKET", "EXECUTION"), default="PREMARKET")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--force", action="store_true", help="Re-run even if slot already completed")
    ap.add_argument("--payload-only", action="store_true", help="Stage 2 only — no Fable call")
    ap.add_argument(
        "--replay",
        action="store_true",
        help="staleness_anchor=scan_plus (dated rejection-log replay)",
    )
    ap.add_argument(
        "--backfill-store",
        action="store_true",
        help="Re-emit missing aether_offpool_coach events from trace jsonl (no Fable re-call)",
    )
    args = ap.parse_args()

    today_pst = dt.datetime.now(PST).date()
    td = dt.date.fromisoformat(args.date) if args.date else today_pst

    if args.backfill_store:
        actions = backfill_store_emits(td)
        print({"trade_date": td.isoformat(), "actions": actions})
        return

    anchor = "scan_plus" if args.replay or (args.date and args.date != today_pst.isoformat()) else "now"
    track = not args.replay and not (args.date and args.date != today_pst.isoformat())

    if args.loop and not args.once:
        scheduler_loop()
        return

    if args.once or not args.loop:
        result = run_for_date(
            td,
            window=args.window,
            force=args.force,
            skip_fable=args.payload_only,
            staleness_anchor=anchor,
            track_completion=track and not args.payload_only,
        )
        print(result)
        return

    scheduler_loop()


if __name__ == "__main__":
    main()
