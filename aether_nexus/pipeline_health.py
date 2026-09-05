"""Aether pipeline heartbeat — last success/failure per compile lane."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
JOURNAL_GRID = BASE_DIR / "traces" / "premarket_ab" / "journal_grid.jsonl"
JOURNAL_SONNET = BASE_DIR / "traces" / "premarket_ab" / "journal_sonnet.jsonl"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _last_journal_date(path: Path) -> str | None:
    if not path.is_file():
        return None
    last: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        d = row.get("date")
        if isinstance(d, str):
            last = d
    return last


def lane_snapshot(state_path: Path, journal_path: Path | None, *, lane: str) -> dict[str, Any]:
    state = _read_json(state_path) if state_path.is_file() else {}
    snap: dict[str, Any] = {
        "lane": lane,
        "last_success_ts": state.get("last_success_ts"),
        "last_success_date": state.get("last_success_date"),
        "last_failure_ts": state.get("last_failure_ts"),
        "last_failure_date": state.get("last_failure_date"),
        "last_failure_reason": state.get("last_failure_reason"),
        "completed_dates": state.get("completed_dates") or [],
        "failed_dates": state.get("failed_dates") or [],
    }
    if journal_path:
        snap["last_journal_date"] = _last_journal_date(journal_path)
    return snap


def _last_completed_date(state: dict[str, Any]) -> str | None:
    if state.get("last_success_date"):
        return str(state["last_success_date"])
    completed = state.get("completed") or {}
    if isinstance(completed, dict) and completed:
        return max(str(k) for k in completed.keys())
    dates = state.get("completed_dates") or []
    if isinstance(dates, list) and dates:
        return max(str(d) for d in dates)
    return None


from store_query import store_query_one  # noqa: E402


def _latest_store_ts(kind: str) -> str | None:
    row = store_query_one(
        "SELECT ts FROM events WHERE source='aether' AND kind=? ORDER BY id DESC LIMIT 1",
        (kind,),
    )
    if not row or row[0] is None:
        return None
    try:
        return dt.datetime.fromtimestamp(float(row[0]), tz=dt.timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


def _latest_store_event(
    kind: str,
    *,
    date_json: str = "$.date",
) -> tuple[str | None, str | None]:
    """Return (trade_date, event_ts_iso) for newest store event of kind."""
    row = store_query_one(
        "SELECT ts, json_extract(payload, ?) FROM events "
        "WHERE source='aether' AND kind=? ORDER BY id DESC LIMIT 1",
        (date_json, kind),
    )
    if not row:
        return None, None
    ts_iso = None
    if row[0] is not None:
        try:
            ts_iso = dt.datetime.fromtimestamp(float(row[0]), tz=dt.timezone.utc).isoformat()
        except (ValueError, TypeError):
            ts_iso = None
    trade_date = str(row[1]) if row[1] else None
    if not trade_date and ts_iso:
        from aether_shared import EST

        trade_date = dt.datetime.fromisoformat(ts_iso).astimezone(EST).date().isoformat()
    return trade_date, ts_iso


def _latest_store_event_offpool_deepseek() -> tuple[str | None, str | None]:
    """Newest aether_offpool store row for deepseek-v4 lane only (post CC retire D1b)."""
    row = store_query_one(
        "SELECT ts, json_extract(payload, '$.date') FROM events "
        "WHERE source='aether' AND kind='aether_offpool' "
        "AND json_extract(payload, '$.lane')='deepseek-v4' "
        "ORDER BY id DESC LIMIT 1",
    )
    if not row:
        return None, None
    ts_iso = None
    if row[0] is not None:
        try:
            ts_iso = dt.datetime.fromtimestamp(float(row[0]), tz=dt.timezone.utc).isoformat()
        except (ValueError, TypeError):
            ts_iso = None
    trade_date = str(row[1]) if row[1] else None
    if not trade_date and ts_iso:
        from aether_shared import EST

        trade_date = dt.datetime.fromisoformat(ts_iso).astimezone(EST).date().isoformat()
    return trade_date, ts_iso


def _merge_offpool_deepseek_with_store(snap: dict[str, Any]) -> dict[str, Any]:
    store_date, store_ts = _latest_store_event_offpool_deepseek()
    if store_date:
        snap["last_success_date"] = max(
            str(snap.get("last_success_date") or ""),
            store_date,
        ) or store_date
        snap["store_last_success_date"] = store_date
    if store_ts:
        snap["store_last_success_ts"] = store_ts
        if not snap.get("last_success_ts"):
            snap["last_success_ts"] = store_ts
    return snap


def _merge_lane_with_store(
    snap: dict[str, Any],
    kind: str,
    *,
    date_json: str = "$.date",
) -> dict[str, Any]:
    store_date, store_ts = _latest_store_event(kind, date_json=date_json)
    if store_date:
        snap["last_success_date"] = max(
            str(snap.get("last_success_date") or ""),
            store_date,
        ) or store_date
        snap["store_last_success_date"] = store_date
    if store_ts:
        snap["store_last_success_ts"] = store_ts
        if not snap.get("last_success_ts"):
            snap["last_success_ts"] = store_ts
    return snap


def _latest_brief_date_from_store() -> str | None:
    row = store_query_one(
        "SELECT json_extract(payload, '$.date') FROM events "
        "WHERE source='aether' AND kind IN ('aether_brief','aether_brief_dryrun') "
        "AND json_extract(payload, '$.date') IS NOT NULL "
        "ORDER BY id DESC LIMIT 1"
    )
    return str(row[0]) if row and row[0] else None


def pipeline_health() -> dict[str, Any]:
    from aether_shared import EST

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    today = dt.datetime.now(EST).date().isoformat()
    grid_raw = _read_json(BASE_DIR / "premarket_compile_state.json")
    grid = lane_snapshot(
        BASE_DIR / "premarket_compile_state.json",
        JOURNAL_GRID,
        lane="premarket_grid",
    )
    if not grid.get("last_success_date"):
        grid["last_success_date"] = _last_completed_date(grid_raw)
    grid = _merge_lane_with_store(grid, "aether_premarket_grid")
    sonnet = lane_snapshot(
        BASE_DIR / "premarket_sonnet_state.json",
        JOURNAL_SONNET,
        lane="premarket_sonnet",
    )
    sonnet_raw = _read_json(BASE_DIR / "premarket_sonnet_state.json")
    if not sonnet.get("last_success_date"):
        sonnet["last_success_date"] = _last_completed_date(sonnet_raw)
    sonnet = _merge_lane_with_store(sonnet, "aether_premarket_sonnet")
    post_market = lane_snapshot(
        BASE_DIR / "post_market_summary_state.json",
        None,
        lane="post_market_daily",
    )
    post_raw = _read_json(BASE_DIR / "post_market_summary_state.json")
    if not post_market.get("last_success_date"):
        post_market["last_success_date"] = _last_completed_date(post_raw)
    latest_brief = _latest_brief_date_from_store()
    if latest_brief:
        post_market["last_success_date"] = max(
            str(post_market.get("last_success_date") or ""),
            latest_brief,
        ) or latest_brief
    paper_daily_raw = _read_json(BASE_DIR.parent / "aether-paper" / "state" / "paper_daily_state.json")
    paper_daily = lane_snapshot(
        BASE_DIR.parent / "aether-paper" / "state" / "paper_daily_state.json",
        None,
        lane="paper_daily",
    )
    if not paper_daily.get("last_success_date"):
        paper_daily["last_success_date"] = _last_completed_date(paper_daily_raw)
    paper_daily["completed"] = paper_daily_raw.get("completed") or {}
    paper_crypto_raw = _read_json(BASE_DIR.parent / "aether-paper" / "state" / "crypto_cli_daily_state.json")
    paper_crypto = lane_snapshot(
        BASE_DIR.parent / "aether-paper" / "state" / "crypto_cli_daily_state.json",
        None,
        lane="paper_crypto_cli",
    )
    if not paper_crypto.get("last_success_date"):
        paper_crypto["last_success_date"] = _last_completed_date(paper_crypto_raw)
    paper_crypto["completed"] = paper_crypto_raw.get("completed") or {}
    earnings = lane_snapshot(
        BASE_DIR / "sonnet_earnings_state.json",
        None,
        lane="sonnet_earnings",
    )
    offpool_raw = _read_json(BASE_DIR / "offpool_state.json")
    offpool = lane_snapshot(
        BASE_DIR / "offpool_state.json",
        None,
        lane="offpool",
    )
    offpool["last_success_date"] = _last_completed_date(offpool_raw)
    offpool = _merge_offpool_deepseek_with_store(offpool)
    offpool_coach_raw = _read_json(BASE_DIR / "offpool_coach_state.json")
    offpool_coach = lane_snapshot(
        BASE_DIR / "offpool_coach_state.json",
        None,
        lane="offpool_coach",
    )
    offpool_coach["last_success_date"] = _last_completed_date(offpool_coach_raw)
    offpool_coach["last_run"] = offpool_coach_raw.get("last_run")
    offpool_coach["completed_slots"] = offpool_coach_raw.get("completed_slots") or {}
    offpool_coach["trial_start_date"] = offpool_coach_raw.get("trial_start_date")
    coach_today = today
    coach_slots = offpool_coach["completed_slots"]
    coach_pre_done = f"{coach_today}:PREMARKET" in coach_slots
    coach_exe_done = f"{coach_today}:EXECUTION" in coach_slots
    coach_trial_start = offpool_coach_raw.get("trial_start_date") or os.getenv("OFFPOOL_COACH_TRIAL_START", "2026-07-17")
    # Retired/sealed coach must not appear as perpetual stale (catchup noise).
    _coach_req = (os.getenv("OFFPOOL_COACH_REQUIRED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    _coach_status = (
        str(offpool_coach_raw.get("status") or os.getenv("OFFPOOL_COACH_STATUS") or "retired")
        .strip()
        .lower()
    )
    coach_active = bool(
        _coach_req
        and _coach_status not in ("retired", "disabled", "off", "sealed")
        and coach_today >= coach_trial_start
    )
    offpool_coach["status"] = "active" if coach_active else (_coach_status or "retired")
    offpool_coach["required"] = coach_active
    dryrun_hb = _read_json(BASE_DIR / "dryrun_state" / "heartbeat.json")
    scan_ts = dryrun_hb.get("last_scan_ts") or dryrun_hb.get("updated_at")
    if not scan_ts:
        scan_ts = _latest_store_ts("aether_scan")
    pool_signals = BASE_DIR / "pool_signals.json"
    if not scan_ts and pool_signals.is_file():
        scan_ts = dt.datetime.fromtimestamp(
            pool_signals.stat().st_mtime, tz=dt.timezone.utc
        ).isoformat()
    now_est = dt.datetime.now(EST)
    import pytz

    now_pst = dt.datetime.now(pytz.timezone("US/Pacific"))
    from daemon_schedule import parse_hhmm, slot_due

    def _stale_after(schedule: str, done: bool) -> bool:
        if now_est.weekday() >= 5:
            return False
        h, m = parse_hhmm(schedule)
        return slot_due(now_est, h, m) and not done

    def _stale_after_pst(schedule: str, done: bool) -> bool:
        if now_pst.weekday() >= 5:
            return False
        h, m = parse_hhmm(schedule)
        return slot_due(now_pst, h, m) and not done

    post_done = post_market.get("last_success_date") == today
    off_done = offpool.get("last_success_date") == today
    earn_done = earnings.get("last_success_date") == today
    paper_done = paper_daily.get("last_success_date") == today or (
        isinstance(paper_daily.get("completed"), dict) and today in paper_daily.get("completed", {})
    )
    crypto_cli_done = paper_crypto.get("last_success_date") == today or (
        isinstance(paper_crypto.get("completed"), dict) and today in paper_crypto.get("completed", {})
    )
    schedules = {
        "premarket_sonnet": os.getenv("PREMARKET_SONNET_TIME", "06:40"),
        "premarket_grid": os.getenv("PREMARKET_COMPILE_TIME", "06:45"),
        "sonnet_earnings": os.getenv("SONNET_EARNINGS_TIME", "06:30"),
        "paper_crypto_cli": os.getenv("CRYPTO_PAPER_CLI_TIME", "09:10"),
        "post_market": os.getenv("POST_MARKET_SUMMARY_TIME", "16:40"),
        "offpool": os.getenv("OFFPOOL_TIME", "17:15"),
        "offpool_coach_pst": os.getenv("PREMARKET_WINDOW_PST", "06:20"),
        "paper_daily": os.getenv("PAPER_DAILY_TIME", "16:40"),
    }
    coach_schedule = schedules["offpool_coach_pst"]
    coach_exe_schedule = os.getenv("EXEC_WINDOW_PST", "07:15")
    stale_post_market = _stale_after(schedules["post_market"], post_done)
    stale_offpool = _stale_after(schedules["offpool"], off_done)
    stale_offpool_coach = (
        coach_active
        and _stale_after_pst(coach_schedule, coach_pre_done)
        and now_pst.weekday() < 5
    )
    stale_offpool_coach_execution = (
        coach_active
        and _stale_after_pst(coach_exe_schedule, coach_exe_done)
        and now_pst.weekday() < 5
    )
    stale_earnings = _stale_after(schedules["sonnet_earnings"], earn_done)
    stale_paper_daily = _stale_after(schedules["paper_daily"], paper_done)
    stale_paper_crypto_cli = _stale_after(schedules["paper_crypto_cli"], crypto_cli_done)
    stale_premarket_grid = _stale_after(schedules["premarket_grid"], grid.get("last_success_date") == today)
    stale_premarket_sonnet = _stale_after(schedules["premarket_sonnet"], sonnet.get("last_success_date") == today)
    try:
        from caliber_lock import caliber_proof_status

        caliber = caliber_proof_status()
    except Exception:
        caliber = {"caliber_locked": False, "checks": [], "banner": "记分层 未锁定 · caliber 自检失败"}
    return {
        "status": "ok",
        "checked_at": now,
        "today": today,
        "caliber_proof": caliber,
        "premarket_grid": grid,
        "premarket_sonnet": sonnet,
        "post_market_daily": post_market,
        "paper_daily": paper_daily,
        "paper_crypto_cli": paper_crypto,
        "sonnet_earnings": earnings,
        "offpool": offpool,
        "offpool_coach": offpool_coach,
        "pool_scan": {"last_success_ts": scan_ts, "lane": "pool_scan"},
        "stale_premarket_grid": stale_premarket_grid,
        "stale_premarket_sonnet": stale_premarket_sonnet,
        "stale_post_market": stale_post_market,
        "stale_offpool": stale_offpool,
        "stale_offpool_coach": stale_offpool_coach,
        "stale_offpool_coach_execution": stale_offpool_coach_execution,
        "stale_sonnet_earnings": stale_earnings,
        "stale_paper_daily": stale_paper_daily,
        "stale_paper_crypto_cli": stale_paper_crypto_cli,
        "schedules_est": schedules,
    }
