#!/usr/bin/env python3
"""
Post-market summary daemon v1 — read same-day Aether scan log, summarize via :8501 Aster,
field-level triple vote, contract_gate egress, Telegram + traces/daemon/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from daemon_schedule import parse_hhmm, slot_due

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
GATEWAY_DIR = REPO_ROOT / "grid-sovereign-runtime" / "gateway"
PAPER_ROOT = REPO_ROOT / "aether-paper"
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))
if PAPER_ROOT.is_dir() and str(PAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(PAPER_ROOT))

from contract_gate import apply_contract_gate, has_trade_action_leak  # noqa: E402

from aether_shared import EST, atomic_write_json, send_notification  # noqa: E402
from aether_grid_emit import brief_items_from_final, emit_brief  # noqa: E402
from grid_compile_client import compile_postmarket_review  # noqa: E402
from premarket_ab_summary import (  # noqa: E402
    build_premarket_ab_summary,
    format_premarket_ab_brief_text,
    premarket_ab_brief_items,
)
from deepseek_performance_summary import (  # noqa: E402
    build_deepseek_performance_summary,
    deepseek_performance_brief_items,
    format_deepseek_performance_text,
)

GRID_EVENTS = os.getenv("GRID_EVENTS", "http://127.0.0.1:8501/store/events")


def _grid_emit(kind: str, **payload: Any) -> None:
    """Fleet heartbeat (source=post_market), not shown in aether.html."""
    try:
        body = json.dumps(
            {"source": "post_market", "kind": kind, "payload": payload},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            GRID_EVENTS,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception as exc:
        logger.debug("grid heartbeat skipped: %s", exc)

try:
    from aether_dryrun import is_trading_day
except Exception:
    def is_trading_day(d: dt.date | None = None) -> bool:
        d = d or dt.datetime.now(EST).date()
        return d.weekday() < 5

logger = logging.getLogger("PostMarketSummary")

GATEWAY_URL = os.getenv("GARDEN_GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
GATEWAY_MODEL = os.getenv("ASTER_GATEWAY_MODEL", "demo/aster")
GATEWAY_TIMEOUT = float(os.getenv("POST_MARKET_GATEWAY_TIMEOUT", "120"))
VOTE_ROUNDS = 3
DRY_RUN_MAX_DAYS = int(os.getenv("POST_MARKET_DRY_RUN_DAYS", "5"))
POST_MARKET_TIME = os.getenv("POST_MARKET_SUMMARY_TIME", "16:40")
POST_MARKET_MIN_LOG_LINES = int(os.getenv("POST_MARKET_MIN_LOG_LINES", "20"))

DRYRUN_LOG_PATHS = [
    BASE_DIR / "dryrun_state" / "dryrun.log",
    BASE_DIR / "dryrun.log",
]
LIVE_LOG_PATHS = [
    BASE_DIR / "nexus_state" / "nexus.log",
    BASE_DIR / "live.log",
]
REJECTION_LOG_DIR = BASE_DIR / "logs" / "rejections"
PREMARKET_JOURNAL_GRID = BASE_DIR / "traces" / "premarket_ab" / "journal_grid.jsonl"
PREMARKET_SCORE_RE = re.compile(
    r"盘前热度\s*([\d.]+)|BFS[^0-9]*([\d.]+)|评分\s*([\d.]+)|score=([\d.]+)",
    re.I,
)
TRACE_DIR = REPO_ROOT / "grid-sovereign-runtime" / "traces" / "daemon"

DRY_RUN_IGNORE_SUSPECT = frozenset({"rehearsal_route", "log_anomaly"})
EXPECTED_DRY_RUN_ANOMALIES = (
    "dry run mode detected",
    "pool scan window",
)
POST_MARKET_TASK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "post_market_summary",
            "description": "Structured post-market scan summary (daemon task budget).",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]
STATE_PATH = BASE_DIR / "post_market_summary_state.json"
STATE_TEST_DIR = BASE_DIR / "state_test"
_test_mode = False


def _paper_brief_items() -> list[dict[str, Any]]:
    try:
        from paper.summary import paper_brief_items

        return paper_brief_items()
    except Exception as exc:
        logger.warning("paper brief items skipped: %s", exc)
        return []


def _paper_journal_block() -> str:
    try:
        from paper.summary import paper_journal_block

        return paper_journal_block()
    except Exception as exc:
        logger.debug("paper journal skipped: %s", exc)
        return ""


def _default_state() -> dict[str, Any]:
    return {"dry_run_days_completed": 0, "dry_run_days_log": [], "completed_dates": []}


def set_test_mode(enabled: bool) -> None:
    global _test_mode
    _test_mode = bool(enabled)


def is_test_mode() -> bool:
    return _test_mode


def _active_state_path() -> Path:
    if _test_mode:
        return STATE_TEST_DIR / "post_market_summary_state.json"
    return STATE_PATH


def _normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    out = dict(state)
    if "dry_run_days_log" not in out and "dry_run_dates" in out:
        out["dry_run_days_log"] = list(out.pop("dry_run_dates") or [])
    log = [str(d) for d in (out.get("dry_run_days_log") or []) if d]
    out["dry_run_days_log"] = sorted(dict.fromkeys(log))
    out["dry_run_days_completed"] = len(out["dry_run_days_log"])
    return out


def record_dry_run_day(state: dict[str, Any], trade_date: dt.date) -> None:
    log = state.setdefault("dry_run_days_log", [])
    dkey = trade_date.isoformat()
    if dkey not in log:
        log.append(dkey)
        log.sort()
    state["dry_run_days_completed"] = len(log)

SCORE_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2} .+ - INFO -\s+(\w+): score=([\d.]+)",
)
STAGE3_DONE = re.compile(
    r"Stage 3 done: passing=(\d+) filtered=(\d+) fetch_fail=(\d+) top=(\d+)",
)
WARN_ERR = re.compile(r"^\d{4}-\d{2}-\d{2} .+ - (WARNING|ERROR) - (.+)$")

SUMMARY_KEYS = ("candidate_count", "top_symbol", "top_score", "anomaly_flags", "data_suspect")

SCAN_INTEGRITY_FLAGS = frozenset({
    "SCAN_ABORTED",
    "UNIVERSE_EMPTY",
    "SP500_UNIVERSE_EMPTY",
    "SSL_CERTIFICATE_VERIFY_FAILED",
})

POOL_SIGNALS_PATH = BASE_DIR / "dryrun_state" / "pool_signals.json"
SIGNALS_PATH = BASE_DIR / "dryrun_state" / "signals.json"

# WARNING+ log themes to surface on Telegram (subject → counter). False positives ignored.
FLAG_THETA_UNIT = re.compile(r"theta-unit check .+ ratio=([\d.]+)", re.I)
IGNORE_FLAG_SUBSTRINGS = (
    "theta-unit check",  # handled by ratio whitelist
    "Stage 1 fallback",
    "Telegram send failed",
)

SYSTEM_PROMPT = """You summarize Aether Nexus scan logs for post-market review.
Reply with ONLY one JSON object. No markdown fences. No prose. No extra keys.

Required schema (exactly these 5 keys):
{
  "candidate_count": <integer, count of top scored candidates in the last scan>,
  "top_symbol": <string ticker or empty string if none>,
  "top_score": <number, highest score from log>,
  "anomaly_flags": <array of strings: WARN/ERROR themes from the log>,
  "data_suspect": <boolean: true if log looks incomplete or contradictory>
}
"""


def summary_from_ground(ground: dict[str, Any]) -> dict[str, Any]:
    out = {
        "candidate_count": int(ground.get("candidate_count", 0)),
        "top_symbol": str(ground.get("top_symbol") or "").strip().upper(),
        "top_score": float(ground.get("top_score", 0)),
        "anomaly_flags": list(ground.get("anomaly_flags") or [])[:30],
        "data_suspect": bool(ground.get("candidate_source") == "premarket_journal"),
    }
    src = ground.get("candidate_source")
    if src:
        out["candidate_source"] = str(src)
    return {k: out[k] for k in SUMMARY_KEYS if k in out} | (
        {"candidate_source": out["candidate_source"]} if out.get("candidate_source") else {}
    )


def should_skip_gateway_audit(log_ground: dict[str, Any], ground: dict[str, Any]) -> bool:
    """Log scan empty but premarket / fact ground exists — skip 8501 triple vote."""
    if log_ground.get("top_symbol") or log_ground.get("candidate_count", 0) > 0:
        return False
    return bool(ground.get("top_symbol") or ground.get("candidate_count", 0) > 0)


def _live_mode_requested() -> bool:
    return os.getenv("POST_MARKET_LIVE", "").lower() in ("1", "true", "yes")


def resolve_effective_dry_run(*, cli_dry_run: bool) -> bool:
    """Fix 1: trace dry_run must match the log source we deliberately read."""
    if _live_mode_requested():
        return False
    if cli_dry_run:
        return True
    return os.getenv("POST_MARKET_SUMMARY_DRY_RUN", "true").lower() in ("1", "true", "yes")


def resolve_log_paths(*, dry_run: bool) -> tuple[list[Path], str]:
    if dry_run:
        found = [p for p in DRYRUN_LOG_PATHS if p.is_file()]
        return (found or [DRYRUN_LOG_PATHS[0]], "dryrun")
    found = [p for p in LIVE_LOG_PATHS if p.is_file()]
    if found:
        return found, "live"
    raise FileNotFoundError(
        "POST_MARKET_LIVE=1 but no live log found under nexus_state/ or live.log"
    )


def _read_log_paths(*, dry_run: bool) -> list[Path]:
    paths, _ = resolve_log_paths(dry_run=dry_run)
    return paths


def check_run_window(*, force: bool) -> tuple[bool, str | None]:
    """Fix 4: refuse scheduled-style runs before post-market window unless --force."""
    if force:
        return True, None
    hour, minute = _parse_hhmm(POST_MARKET_TIME)
    now = dt.datetime.now(EST)
    scheduled = dt.time(hour, minute)
    if now.time() < scheduled:
        return False, f"before_post_market_window ({POST_MARKET_TIME} EST)"
    return True, None


def _log_timestamp(line: str) -> dt.datetime | None:
    m = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})", line)
    if not m:
        return None
    try:
        y, mo, d = m.group(1).split("-")
        return dt.datetime(
            int(y),
            int(mo),
            int(d),
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
            tzinfo=EST,
        )
    except ValueError:
        return None


def assess_log_session(
    lines: list[str], *, dry_run: bool, supplemental_ok: bool = False,
) -> tuple[bool, str | None]:
    if len(lines) < POST_MARKET_MIN_LOG_LINES:
        if supplemental_ok:
            return True, None
        return False, f"thin_log ({len(lines)} lines)"
    if dry_run:
        return True, None
    if extract_last_scan_block(lines):
        return True, None
    last_ts = None
    for line in reversed(lines):
        last_ts = _log_timestamp(line)
        if last_ts:
            break
    if last_ts and last_ts.time() < dt.time(15, 30):
        return False, f"log_stale_before_close ({last_ts.strftime('%H:%M')} EST)"
    return True, None


def filter_dry_run_anomalies(flags: list[str], *, dry_run: bool) -> list[str]:
    if not dry_run:
        return list(flags)
    out: list[str] = []
    for flag in flags:
        low = str(flag).lower()
        if any(exp in low for exp in EXPECTED_DRY_RUN_ANOMALIES):
            continue
        out.append(flag)
    return out


def effective_suspect_reasons(reasons: list[str], *, dry_run: bool) -> list[str]:
    if not dry_run:
        return list(reasons)
    return [r for r in reasons if r not in DRY_RUN_IGNORE_SUSPECT]


def reconcile_dry_run_final(
    final: dict[str, Any],
    ground: dict[str, Any],
    *,
    rehearsal: bool,
    scan_integrity_failed: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """When audit votes empty, fill from log / premarket ground truth."""
    return reconcile_audit_final(
        final,
        ground,
        rehearsal=rehearsal,
        scan_integrity_failed=scan_integrity_failed,
        dry_run=dry_run,
    )


def reconcile_audit_final(
    final: dict[str, Any],
    ground: dict[str, Any],
    *,
    rehearsal: bool,
    scan_integrity_failed: bool = False,
    dry_run: bool = False,
    lines: list[str] | None = None,
    trade_date: dt.date | None = None,
) -> dict[str, Any]:
    if scan_integrity_failed:
        return apply_stale_candidate_context(
            final,
            ground,
            scan_integrity_failed=True,
            lines=lines,
            trade_date=trade_date,
        )
    out = dict(final)
    votes_empty = not (out.get("top_symbol") or out.get("candidate_count", 0) > 0)
    ground_has = bool(ground.get("top_symbol") or ground.get("candidate_count", 0) > 0)
    if votes_empty and ground_has:
        out["candidate_count"] = int(ground.get("candidate_count", 0))
        out["top_symbol"] = str(ground.get("top_symbol") or "").strip().upper()
        out["top_score"] = float(ground.get("top_score", 0))
        src = str(ground.get("candidate_source") or "")
        if src == "premarket_journal":
            out["data_suspect"] = True
            out["candidate_source"] = src
            flags = list(out.get("anomaly_flags") or [])
            if "premarket_fallback" not in flags:
                flags.append("premarket_fallback")
            out["anomaly_flags"] = flags[:30]
        elif rehearsal or dry_run:
            out["data_suspect"] = False
    return out


def ground_from_premarket(trade_date: str) -> dict[str, Any]:
    """Fallback ground when nexus.log has no scan block (premarket journal)."""
    if not PREMARKET_JOURNAL_GRID.is_file():
        return {}
    scores: list[tuple[str, float]] = []
    for line in PREMARKET_JOURNAL_GRID.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("date") != trade_date:
            continue
        sym = str(row.get("sym") or "").strip().upper()
        if not sym:
            continue
        note = str(row.get("note") or "")
        m = PREMARKET_SCORE_RE.search(note)
        score = 50.0
        if m:
            raw = next((g for g in m.groups() if g), None)
            if raw:
                try:
                    score = float(raw)
                except ValueError:
                    pass
        scores.append((sym, score))
    if not scores:
        return {}
    scores.sort(key=lambda x: x[1], reverse=True)
    top_sym, top_score = scores[0]
    return {
        "candidate_count": len(scores),
        "top_symbol": top_sym,
        "top_score": top_score,
        "anomaly_flags": ["premarket_fallback"],
        "parsed_score_rows": scores,
        "last_scan_aborted": False,
        "scan_valid": True,
        "candidate_source": "premarket_journal",
    }


def ground_from_store_scan(trade_date: str) -> dict[str, Any]:
    """Fallback when nexus.log is stale — read same-day aether_scan rows from grid_store."""
    from store_query import store_query_all

    try:
        d = dt.date.fromisoformat(trade_date)
    except ValueError:
        return {}
    start = dt.datetime.combine(d, dt.time.min, tzinfo=EST).timestamp()
    end = start + 86400.0
    rows = store_query_all(
        "SELECT payload FROM events WHERE source='aether' AND kind='aether_scan' "
        "AND ts >= ? AND ts < ? ORDER BY id DESC LIMIT 30",
        (start, end),
    )
    best_scores: list[tuple[str, float]] = []
    label = ""
    for (payload_raw,) in rows:
        if not payload_raw:
            continue
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            continue
        scan_rows = payload.get("rows") or []
        if not scan_rows:
            continue
        scores: list[tuple[str, float]] = []
        for row in scan_rows:
            sym = str(row.get("sym") or "").strip().upper()
            if not sym:
                continue
            try:
                score = float(row.get("score") or 0)
            except (TypeError, ValueError):
                score = 0.0
            scores.append((sym, score))
        if not scores:
            continue
        scores.sort(key=lambda x: x[1], reverse=True)
        if len(scores) > len(best_scores):
            best_scores = scores
            label = str(payload.get("label") or "store_scan")
    if not best_scores:
        return {}
    top_sym, top_score = best_scores[0]
    return {
        "candidate_count": len(best_scores),
        "top_symbol": top_sym,
        "top_score": top_score,
        "anomaly_flags": [],
        "parsed_score_rows": best_scores,
        "last_scan_aborted": False,
        "scan_valid": True,
        "candidate_source": "store_scan",
        "scan_label": label,
    }


def merge_ground_truth(*grounds: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for g in grounds:
        if not g:
            continue
        if not out:
            out = dict(g)
            continue
        if out.get("top_symbol") or out.get("candidate_count", 0) > 0:
            continue
        out = dict(g)
    return out or {
        "candidate_count": 0,
        "top_symbol": "",
        "top_score": 0.0,
        "anomaly_flags": [],
        "parsed_score_rows": [],
        "last_scan_aborted": False,
        "scan_valid": True,
    }


def supplemental_log_lines(trade_date: dt.date) -> list[str]:
    """Rejection summaries when nexus.log is thin on scan activity."""
    prefix = trade_date.isoformat()
    out: list[str] = []
    if not REJECTION_LOG_DIR.is_dir():
        return out
    for fp in sorted(REJECTION_LOG_DIR.glob(f"{prefix}_*.jsonl")):
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines()[:200]:
            if line.strip():
                out.append(f"{prefix} 16:00:00,000 - INFO - rejection excerpt {line[:240]}")
    return out


def is_rehearsal_meta(meta: dict[str, Any]) -> bool:
    gm = meta.get("grid_meta") or {}
    if str(gm.get("budget_route") or "") == "task":
        return False
    if gm.get("draft_only"):
        return True
    if str(gm.get("computed_verdict") or "") == "DRAFT_ECHO":
        return True
    if gm.get("production") is False:
        return True
    if str(gm.get("route_class") or "") == "unsafe_debug":
        return True
    return False


def audit_rehearsal(metas: list[dict[str, Any]]) -> bool:
    return any(is_rehearsal_meta(m) for m in metas)


def compute_trust_credit(
    *,
    dry_run: bool,
    rehearsal: bool,
    tier: str,
    final: dict[str, Any],
    suspect_reasons: list[str],
    scan_integrity_failed: bool = False,
) -> bool:
    if dry_run or rehearsal or scan_integrity_failed:
        return False
    if tier == "red":
        return False
    if final.get("data_suspect"):
        return False
    if any(r in suspect_reasons for r in ("rehearsal_route", "thin_log", "premature_run")):
        return False
    return True


def _lines_for_date(trade_date: dt.date, *, dry_run: bool) -> list[str]:
    prefix = trade_date.isoformat()
    lines: list[str] = []
    for path in _read_log_paths(dry_run=dry_run):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("cannot read %s: %s", path, exc)
            continue
        for line in text.splitlines():
            if line.startswith(prefix):
                lines.append(line)
    if not dry_run and len(lines) < POST_MARKET_MIN_LOG_LINES:
        extra = supplemental_log_lines(trade_date)
        if extra:
            lines.extend(extra)
        for path in DRYRUN_LOG_PATHS:
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if line.startswith(prefix) and line not in lines:
                    lines.append(line)
            if len(lines) >= POST_MARKET_MIN_LOG_LINES:
                break
    return lines


def _flag_matches_integrity(flag: str) -> bool:
    upper = str(flag).upper()
    if upper in SCAN_INTEGRITY_FLAGS:
        return True
    if any(token in upper for token in SCAN_INTEGRITY_FLAGS):
        return True
    low = str(flag).lower()
    if "scan aborted" in low or "universe empty" in low:
        return True
    if "ssl" in low and "certificate" in low:
        return True
    return False


def has_scan_integrity_failure(
    final: dict[str, Any],
    ground: dict[str, Any] | None = None,
    lines: list[str] | None = None,
) -> bool:
    for flag in final.get("anomaly_flags") or []:
        if _flag_matches_integrity(flag):
            return True
    if ground:
        for flag in ground.get("anomaly_flags") or []:
            if _flag_matches_integrity(flag):
                return True
        if ground.get("last_scan_aborted"):
            return True
    if lines:
        block = extract_last_scan_block(lines)
        for line in block:
            low = line.lower()
            if "scan aborted" in low or "universe empty" in low:
                return True
    return False


def _last_successful_scan_kind(lines: list[str]) -> str:
    """Infer stale candidate origin when the latest scan aborted."""
    pool_ok = sp500_ok = False
    for line in lines:
        low = line.lower()
        if "pool scan finished" in low or "scheduled pool scan triggered" in low:
            pool_ok = True
        if "bfs sp500 scan finished" in low:
            sp500_ok = True
        if "scan aborted" in low or ("universe empty" in low and "sp500" in low):
            break
    if pool_ok and not sp500_ok:
        return "pool"
    if sp500_ok:
        return "cache"
    return "cache"


def _load_state_candidates(path: Path, trade_date: dt.date) -> tuple[str, list[tuple[str, float]]]:
    if not path.is_file():
        return "", []
    try:
        rounds = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", []
    if not isinstance(rounds, list):
        return "", []
    dkey = trade_date.isoformat()
    for entry in reversed(rounds):
        if not isinstance(entry, dict):
            continue
        scan_time = str(entry.get("scan_time") or "")
        if not scan_time.startswith(dkey):
            continue
        mode = str(entry.get("scan_mode") or path.stem.replace("_signals", ""))
        src = "pool" if mode == "pool" else "cache"
        rows: list[tuple[str, float]] = []
        for c in entry.get("candidates") or []:
            sym = str(c.get("symbol") or "").strip().upper()
            if sym:
                rows.append((sym, float(c.get("score") or 0)))
        if rows:
            return src, rows
    return "", []


def infer_stale_candidate_source(
    ground: dict[str, Any],
    lines: list[str],
    trade_date: dt.date,
) -> str:
    for path in (POOL_SIGNALS_PATH, SIGNALS_PATH):
        src, rows = _load_state_candidates(path, trade_date)
        if rows:
            return src
    return _last_successful_scan_kind(lines) or "cache"


def build_stale_candidate_items(
    ground: dict[str, Any],
    *,
    source: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows: list[tuple[str, float]] = list(ground.get("parsed_score_rows") or [])
    if not rows and ground.get("top_symbol"):
        rows = [(str(ground["top_symbol"]).upper(), float(ground.get("top_score") or 0))]
    items: list[dict[str, Any]] = []
    for sym, score in rows[:limit]:
        items.append(
            {
                "sym": sym,
                "label": "score",
                "value": f"{score:.2f}",
                "note": "缓存候选",
                "dir": 1 if score >= 50 else -1 if score < 35 else 0,
                "src": source,
            }
        )
    return items


def apply_stale_candidate_context(
    final: dict[str, Any],
    ground: dict[str, Any],
    *,
    scan_integrity_failed: bool,
    lines: list[str] | None = None,
    trade_date: dt.date | None = None,
) -> dict[str, Any]:
    out = dict(final)
    if not scan_integrity_failed:
        return out
    source = infer_stale_candidate_source(ground, lines or [], trade_date or dt.datetime.now(EST).date())
    stale_items = build_stale_candidate_items(ground, source=source)
    if stale_items:
        out["candidate_count"] = len(stale_items)
        out["top_symbol"] = stale_items[0]["sym"]
        out["top_score"] = float(stale_items[0]["value"])
    else:
        out["candidate_count"] = 0
        out["top_symbol"] = ""
        out["top_score"] = 0.0
    out["scan_valid"] = False
    out["candidate_source"] = source
    out["stale_candidates"] = stale_items
    out["data_suspect"] = True
    flags = list(out.get("anomaly_flags") or [])
    for token in ("SCAN_ABORTED", "UNIVERSE_EMPTY"):
        if token not in flags:
            flags.append(token)
    out["anomaly_flags"] = flags[:30]
    return out


def parse_log_ground_truth(lines: list[str]) -> dict[str, Any]:
    """Deterministic parse from log for validation / prompt context."""
    scores: list[tuple[str, float]] = []
    stage3_top = 0
    flags: list[str] = []
    for line in lines:
        m = SCORE_LINE.match(line)
        if m:
            scores.append((m.group(1).upper(), float(m.group(2))))
        m3 = STAGE3_DONE.search(line)
        if m3:
            stage3_top = int(m3.group(4))
        we = WARN_ERR.match(line)
        if we:
            body = (we.group(2) or "").strip()
            if body:
                flags.append(f"{we.group(1)}: {body[:120]}")
    top_symbol = scores[-1][0] if scores else ""
    top_score = scores[-1][1] if scores else 0.0
    # Use last scan block's score lines (most recent scan of the day)
    if scores:
        last_scan_scores: list[tuple[str, float]] = []
        for line in reversed(lines):
            m = SCORE_LINE.match(line)
            if m:
                last_scan_scores.insert(0, (m.group(1).upper(), float(m.group(2))))
            elif "scan starting" in line.lower() and last_scan_scores:
                break
        if last_scan_scores:
            scores = last_scan_scores
            top_symbol, top_score = scores[0]
    candidate_count = stage3_top or len(scores)
    last_scan_aborted = False
    block = extract_last_scan_block(lines)
    for line in block:
        low = line.lower()
        if "scan aborted" in low or ("universe empty" in low and "sp500" in low):
            last_scan_aborted = True
            break
    return {
        "candidate_count": candidate_count,
        "top_symbol": top_symbol,
        "top_score": top_score,
        "anomaly_flags": list(dict.fromkeys(flags))[:20],
        "parsed_score_rows": scores,
        "last_scan_aborted": last_scan_aborted,
        "scan_valid": not last_scan_aborted,
    }


def extract_last_scan_block(lines: list[str]) -> list[str]:
    """Lines from the last scan starting marker through end of that scan."""
    if not lines:
        return []
    start_idx = 0
    for i, line in enumerate(lines):
        if re.search(r"scan starting|Scheduled .* scan triggered", line, re.I):
            start_idx = i
    block = lines[start_idx:]
    # Trim to scan finished or cap length
    out: list[str] = []
    for line in block:
        out.append(line)
        if "scan finished" in line.lower() or "scan aborted" in line.lower():
            break
    return out[-80:] if len(out) > 80 else out


def build_user_prompt(lines: list[str], ground: dict[str, Any]) -> str:
    block = extract_last_scan_block(lines)
    if block:
        excerpt = "\n".join(block)
    elif ground.get("parsed_score_rows"):
        excerpt = "\n".join(
            f"{sym}: score={score:.1f} (premarket journal)"
            for sym, score in (ground.get("parsed_score_rows") or [])
        )
    else:
        excerpt = "(no scan block for this date)"
    hint = {
        "candidate_count": ground.get("candidate_count"),
        "top_symbol": ground.get("top_symbol"),
        "top_score": ground.get("top_score"),
        "warn_error_count": len(ground.get("anomaly_flags") or []),
    }
    return (
        f"Trade date: {lines[0][:10] if lines else 'unknown'}\n"
        f"Parsed hint: {json.dumps(hint, ensure_ascii=False)}\n\n"
        f"--- last scan log ---\n{excerpt}\n--- end ---"
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def coerce_summary(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    from earnings_integrity import sanitize_anomaly_flag

    if not isinstance(raw, dict):
        return None
    try:
        out = {
            "candidate_count": int(raw.get("candidate_count", 0)),
            "top_symbol": str(raw.get("top_symbol") or "").strip().upper(),
            "top_score": float(raw.get("top_score", 0)),
            "anomaly_flags": [
                x for x in (sanitize_anomaly_flag(str(f)) for f in (raw.get("anomaly_flags") or []))
                if x
            ],
            "data_suspect": bool(raw.get("data_suspect", False)),
        }
    except (TypeError, ValueError):
        return None
    extra = set(raw.keys()) - set(SUMMARY_KEYS)
    if extra:
        out["data_suspect"] = True
    return out


def gateway_chat(user_prompt: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    from aether_grid_verify import attach_aster_chat_verification

    body = {
        "model": GATEWAY_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "stream": False,
        "response_format": {"type": "json_object"},
        "_grid_unsafe_debug": False,
        "tools": POST_MARKET_TASK_TOOLS,
    }
    meta: dict[str, Any] = {"gateway_url": GATEWAY_URL, "model": GATEWAY_MODEL}
    try:
        body = attach_aster_chat_verification(
            body, gateway_url=f"{GATEWAY_URL}/v1/chat/completions",
        )
    except Exception as exc:
        meta["error"] = str(exc)
        return None, meta
    req = urllib.request.Request(
        f"{GATEWAY_URL}/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=GATEWAY_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        meta["error"] = str(exc)
        return None, meta

    meta["grid_meta"] = payload.get("grid_meta") or {}
    if meta["grid_meta"].get("truncated"):
        meta["truncated"] = True
    choices = payload.get("choices") or []
    text = ""
    if choices:
        text = (choices[0].get("message") or {}).get("content") or ""
    gate = apply_contract_gate(user_prompt, text, route="gateway", route_id=payload.get("id"))
    meta["contract_blocked"] = gate.blocked
    meta["contract_reason"] = gate.reason
    meta["contract_suffix"] = gate.routed_suffix
    if gate.blocked:
        parsed = _extract_json(gate.text)
        return coerce_summary(parsed), meta
    return coerce_summary(_extract_json(text)), meta


def _norm_symbol(v: str) -> str:
    return str(v or "").strip().upper()


def _norm_score(v: float) -> float:
    return round(float(v), 2)


def field_majority(values: list[Any]) -> tuple[Any, bool]:
    """Return (winner, has_majority). Majority = at least 2 of 3 agree."""
    counts = Counter(values)
    winner, count = counts.most_common(1)[0]
    return winner, count >= 2


def triple_vote(user_prompt: str, *, dry_run: bool) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    votes: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    for i in range(VOTE_ROUNDS):
        summary, meta = gateway_chat(user_prompt)
        metas.append(meta)
        if summary is None:
            votes.append(
                {
                    "candidate_count": 0,
                    "top_symbol": "",
                    "top_score": 0.0,
                    "anomaly_flags": ["gateway_parse_fail"],
                    "data_suspect": True,
                }
            )
        else:
            if meta.get("truncated"):
                summary["data_suspect"] = True
                summary["anomaly_flags"] = list(summary.get("anomaly_flags") or []) + ["gateway_truncated"]
            summary["anomaly_flags"] = filter_dry_run_anomalies(
                list(summary.get("anomaly_flags") or []),
                dry_run=dry_run,
            )
            votes.append(summary)
        time.sleep(0.3)

    cc_vals = [v["candidate_count"] for v in votes]
    sym_vals = [_norm_symbol(v["top_symbol"]) for v in votes]
    score_vals = [_norm_score(v["top_score"]) for v in votes]

    cc, cc_ok = field_majority(cc_vals)
    sym, sym_ok = field_majority(sym_vals)
    sc, sc_ok = field_majority(score_vals)

    flags: list[str] = []
    for v in votes:
        flags.extend(v.get("anomaly_flags") or [])
    flags = list(dict.fromkeys(flags))

    inconsistent = not (cc_ok and sym_ok and sc_ok)
    data_suspect = inconsistent or any(v.get("data_suspect") for v in votes)
    if audit_rehearsal(metas) and not dry_run:
        data_suspect = True
        flags.append("rehearsal_route")
    if any(m.get("contract_blocked") for m in metas):
        data_suspect = True
        flags.append("CONTRACT_GATE_BLOCKED")

    flags = filter_dry_run_anomalies(flags, dry_run=dry_run)

    final = {
        "candidate_count": int(cc),
        "top_symbol": str(sym),
        "top_score": float(sc),
        "anomaly_flags": flags[:30],
        "data_suspect": bool(data_suspect),
    }
    # Strict schema — strip anything else
    final = {k: final[k] for k in SUMMARY_KEYS}

    audit = {
        "votes": votes,
        "vote_meta": metas,
        "majority_ok": {"candidate_count": cc_ok, "top_symbol": sym_ok, "top_score": sc_ok},
        "inconsistent_triple": inconsistent,
    }
    return final, audit, inconsistent


def quarantine_summary(final: dict[str, Any], reason: str) -> dict[str, Any]:
    flags = list(final.get("anomaly_flags") or [])
    if reason not in flags:
        flags.append(reason)
    return {
        "candidate_count": 0,
        "top_symbol": "",
        "top_score": 0.0,
        "anomaly_flags": flags[:30],
        "data_suspect": True,
    }


def _date_label(trade_date: dt.date) -> str:
    return trade_date.strftime("%m-%d")


def make_trace_id(trade_date: dt.date, stamp: str) -> str:
    """Full trace id — maps to traces/daemon/summary_{date}_{stamp}.json"""
    return f"{trade_date.isoformat()}_{stamp}"


def _theta_unit_ignored(line: str) -> bool:
    m = FLAG_THETA_UNIT.search(line)
    if not m:
        return False
    try:
        ratio = float(m.group(1))
    except ValueError:
        return False
    return 0.8 <= ratio <= 1.2


def aggregate_log_flags(lines: list[str]) -> dict[str, Any]:
    """Whitelist WARNING+ from scan log — subject + counts, no adjectives."""
    fetch_symbols: list[str] = []
    skip_symbols: list[str] = []
    other: Counter[str] = Counter()

    for line in lines:
        we = WARN_ERR.match(line)
        if not we:
            continue
        level, body = we.group(1), we.group(2)
        if _theta_unit_ignored(body):
            continue
        if any(x in body for x in IGNORE_FLAG_SUBSTRINGS):
            continue

        sym_m = re.search(r"fetch failed:\s*(\w+)", body, re.I)
        if sym_m:
            fetch_symbols.append(sym_m.group(1).upper())
            continue
        skip_m = re.search(r"skip(?:ped)?:\s*(\w+)", body, re.I)
        if skip_m:
            skip_symbols.append(skip_m.group(1).upper())
            continue
        if level == "ERROR":
            other["log_error"] += 1
        else:
            key = re.sub(r"\s+", "_", body.split("[")[0].split(":")[0].strip()[:32].lower())
            other[key or "warning"] += 1

    return {
        "fetch_fail": list(dict.fromkeys(fetch_symbols)),
        "skip": list(dict.fromkeys(skip_symbols)),
        "other": dict(other),
    }


def compute_suspect_reasons(
    *,
    final: dict[str, Any],
    audit: dict[str, Any],
    inconsistent: bool,
    metas: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> list[str]:
    reasons: list[str] = []
    votes = audit.get("votes") or []
    gateway_parse_fails = sum(
        1 for v in votes if "gateway_parse_fail" in (v.get("anomaly_flags") or [])
    )
    if gateway_parse_fails:
        reasons.append(f"gateway_parse_fail×{gateway_parse_fails}")
    if inconsistent:
        reasons.append("vote_disagreement")
    if any(m.get("truncated") for m in (metas or [])):
        reasons.append("gateway_truncated")
    if any(m.get("contract_blocked") for m in (metas or [])):
        reasons.append("contract_gate_blocked")
    if any(is_rehearsal_meta(m) for m in (metas or [])) and not dry_run:
        reasons.append("rehearsal_route")
    if "gateway_truncated" in (final.get("anomaly_flags") or []):
        if "gateway_truncated" not in reasons:
            reasons.append("gateway_truncated")
    if not reasons and final.get("data_suspect"):
        reasons.append("log_anomaly")
    return reasons


def classify_telegram_tier(
    *,
    final: dict[str, Any],
    suspect_reasons: list[str],
    log_flags: dict[str, Any],
    quarantined: bool,
    summary_available: bool,
    dry_run: bool = False,
    scan_integrity_failed: bool = False,
) -> str:
    if quarantined:
        return "red"
    if summary_available and final.get("top_symbol"):
        if scan_integrity_failed or not final.get("scan_valid", True):
            return "yellow"
        tier_reasons = effective_suspect_reasons(suspect_reasons, dry_run=dry_run)
        has_noise = (
            bool(tier_reasons)
            or bool(final.get("data_suspect"))
            or bool(log_flags.get("fetch_fail"))
            or bool(log_flags.get("skip"))
            or bool(log_flags.get("other"))
            or bool(final.get("anomaly_flags"))
        )
        return "yellow" if has_noise else "green"
    gateway_fails = sum(
        1 for r in suspect_reasons if r.startswith("gateway_parse_fail")
    )
    if gateway_fails >= 3:
        return "red"
    if not summary_available and not dry_run:
        return "red"
    if not summary_available and dry_run:
        return "yellow"
    if scan_integrity_failed or not final.get("scan_valid", True):
        return "yellow"
    tier_reasons = effective_suspect_reasons(suspect_reasons, dry_run=dry_run)
    has_noise = (
        bool(tier_reasons)
        or (bool(final.get("data_suspect")) and not dry_run)
        or bool(log_flags.get("fetch_fail"))
        or bool(log_flags.get("skip"))
        or bool(log_flags.get("other"))
        or (bool(final.get("anomaly_flags")) and not dry_run)
    )
    if has_noise:
        return "yellow"
    return "green"


def _format_flag_clause(log_flags: dict[str, Any], suspect_reasons: list[str]) -> str:
    parts: list[str] = []
    fetch = log_flags.get("fetch_fail") or []
    if fetch:
        parts.append(f"fetch_fail ×{len(fetch)} ({', '.join(fetch[:6])})")
    skip = log_flags.get("skip") or []
    if skip:
        parts.append(f"skip ×{len(skip)} ({', '.join(skip[:6])})")
    for reason in suspect_reasons:
        if reason.startswith("gateway_parse_fail"):
            parts.append(reason.replace("×", " ×"))
        elif reason == "vote_disagreement":
            parts.append("parse_retry ×1")
        elif reason in DRY_RUN_IGNORE_SUSPECT:
            continue
        elif reason not in ("gateway_truncated", "log_anomaly"):
            parts.append(reason)
    for key, count in sorted((log_flags.get("other") or {}).items()):
        parts.append(f"{key} ×{count}")
    return " · ".join(parts)


def format_notify_message(
    final: dict[str, Any],
    *,
    trade_date: dt.date,
    compiled: str | None,
    ab_text: str,
    deepseek_text: str = "",
) -> str:
    """Telegram/Pushover body — never the red 需要你看一眼 template."""
    dl = _date_label(trade_date)
    sym = final.get("top_symbol") or ""
    cc = int(final.get("candidate_count") or 0)
    score = float(final.get("top_score") or 0)
    if sym and cc:
        head = f"🟡 Aether {dl} · {cc} candidates · top {sym} ({score:.1f})"
    elif sym:
        head = f"🟡 Aether {dl} · top {sym}"
    else:
        head = f"🟡 Aether {dl}"
    parts = [head]
    body = (compiled or "").strip()
    if body:
        parts.append(body)
    ab = (ab_text or "").strip()
    if ab:
        parts.append(ab)
    ds = (deepseek_text or "").strip()
    if ds:
        parts.append(ds)
    return "\n\n".join(parts)


def format_telegram(
    final: dict[str, Any],
    *,
    trade_date: dt.date,
    dry_run: bool,
    trace_id: str,
    trace_rel: str,
    tier: str,
    suspect_reasons: list[str],
    log_flags: dict[str, Any],
    quarantined: bool = False,
    scan_integrity_failed: bool = False,
) -> str:
    """Three-tier Telegram: status line first; message is index, trace file is archive."""
    dr = "[DRY-RUN] " if dry_run else ""
    dl = _date_label(trade_date)
    cc = final.get("candidate_count", 0)
    sym = final.get("top_symbol") or ""
    score = final.get("top_score", 0)
    stale = scan_integrity_failed or not final.get("scan_valid", True)
    source = str(final.get("candidate_source") or "cache")
    summary_bit = ""
    if stale and cc:
        summary_bit = f" · 候选来自{source},非本次扫描产出 · {cc} cached"
        if sym:
            summary_bit += f" · top {sym} ({score:.1f})"
    elif sym and cc:
        summary_bit = f" · {cc} candidates · top {sym} ({score:.1f})"
    elif cc:
        summary_bit = f" · {cc} candidates"

    if tier == "green":
        return f"🟢 {dr}Aether {dl}{summary_bit} · trace {trace_id}"

    if stale:
        status = f"🟡 {dr}Aether {dl} · 本次无有效扫描,数据链路故障"
    else:
        status = {
            "yellow": f"🟡 {dr}Aether {dl} · 有噪音,不用管",
            "red": f"🔴 {dr}Aether {dl} · 需要你看一眼",
        }[tier]
    lines = [status]

    if tier == "red" and (quarantined or not sym):
        lines.append(f"🔴 Aether {dl} · summary unavailable")
        flag_clause = _format_flag_clause(log_flags, suspect_reasons)
        if quarantined:
            flag_clause = (flag_clause + " · " if flag_clause else "") + "raw 已落盘 quarantine"
        if flag_clause:
            lines.append(flag_clause)
        lines.append(f"→ 需要人工: {trace_rel}")
        return "\n".join(lines)

    body = f"{'🟡' if tier == 'yellow' else '🔴'} Aether {dl}{summary_bit}"
    lines.append(body)
    if stale:
        lines.append("候选来自缓存,非本次扫描产出")
    flag_clause = _format_flag_clause(log_flags, suspect_reasons)
    if flag_clause:
        lines.append(f"⚠ {flag_clause}")
    if final.get("data_suspect") and suspect_reasons:
        lines.append(f"reason: {', '.join(suspect_reasons)}")
    lines.append(f"trace {trace_id}")
    return "\n".join(lines)


def load_state() -> dict[str, Any]:
    path = _active_state_path()
    if _test_mode and not path.is_file() and STATE_PATH.is_file():
        try:
            return _normalize_state(json.loads(STATE_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return _default_state()
    if not path.is_file():
        return _default_state()
    try:
        return _normalize_state(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return _default_state()


def save_state(state: dict[str, Any]) -> None:
    if _test_mode:
        STATE_TEST_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(str(_active_state_path()), _normalize_state(state))


def run_for_date(trade_date: dt.date, *, dry_run: bool, force: bool = False) -> dict[str, Any]:
    dry_run = resolve_effective_dry_run(cli_dry_run=dry_run)
    ok_window, window_reason = check_run_window(force=force)
    if not ok_window:
        raise RuntimeError(window_reason or "outside_post_market_window")

    log_paths, log_source = resolve_log_paths(dry_run=dry_run)
    dkey = trade_date.isoformat()
    premarket_ab = build_premarket_ab_summary(dkey)
    deepseek_performance = build_deepseek_performance_summary(dkey)
    lines = _lines_for_date(trade_date, dry_run=dry_run)
    log_ground = parse_log_ground_truth(lines)
    store_ground = ground_from_store_scan(dkey)
    premarket_ground = ground_from_premarket(dkey)
    ground = merge_ground_truth(log_ground, store_ground, premarket_ground)
    log_ok, log_reason = assess_log_session(
        lines,
        dry_run=dry_run,
        supplemental_ok=bool(
            premarket_ground.get("top_symbol") or store_ground.get("top_symbol")
        ),
    )
    pre_integrity_failed = has_scan_integrity_failure({"anomaly_flags": []}, ground, lines)
    user_prompt = build_user_prompt(lines, ground)

    if should_skip_gateway_audit(log_ground, ground):
        final = summary_from_ground(ground)
        audit = {
            "votes": [],
            "vote_meta": [],
            "majority_ok": {},
            "inconsistent_triple": False,
            "skipped": "premarket_ground",
        }
        inconsistent = False
        metas = []
        rehearsal = False
        logger.info("gateway audit skipped — using ground summary top=%s", final.get("top_symbol"))
    else:
        final, audit, inconsistent = triple_vote(user_prompt, dry_run=dry_run)
        metas = audit.get("vote_meta") or []
        rehearsal = audit_rehearsal(metas)
    scan_integrity_failed = (
        pre_integrity_failed
        or has_scan_integrity_failure(final, ground, lines)
    )
    if not should_skip_gateway_audit(log_ground, ground):
        final = reconcile_audit_final(
            final,
            ground,
            rehearsal=rehearsal,
            scan_integrity_failed=scan_integrity_failed,
            dry_run=dry_run,
            lines=lines,
            trade_date=trade_date,
        )
    suspect_reasons = compute_suspect_reasons(
        final=final,
        audit=audit,
        inconsistent=inconsistent,
        metas=metas,
        dry_run=dry_run,
    )
    suspect_reasons = effective_suspect_reasons(suspect_reasons, dry_run=dry_run)
    if not log_ok and log_reason:
        suspect_reasons.append(log_reason)
    if rehearsal and not dry_run:
        suspect_reasons = list(dict.fromkeys(suspect_reasons + ["rehearsal_route"]))
    if suspect_reasons and not dry_run:
        final = dict(final)
        final["data_suspect"] = True
        if rehearsal:
            final["anomaly_flags"] = list(dict.fromkeys(
                list(final.get("anomaly_flags") or []) + ["rehearsal_route"]
            ))

    scan_lines = extract_last_scan_block(lines) or lines
    log_flags = aggregate_log_flags(scan_lines)

    quarantined = False
    quarantine_reason = None
    egress_text = json.dumps(final, ensure_ascii=False)
    if has_trade_action_leak(egress_text):
        quarantined = True
        quarantine_reason = "TRADE_ACTION_LOCAL"
        final = quarantine_summary(final, quarantine_reason)
        suspect_reasons = list(suspect_reasons) + ["TRADE_ACTION_QUARANTINE"]

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(EST).strftime("%Y%m%d_%H%M%S")
    trace_id = make_trace_id(trade_date, stamp)
    trace_path = TRACE_DIR / f"summary_{trade_date.isoformat()}_{stamp}.json"
    trace_rel = f"traces/daemon/{trace_path.name}"

    summary_available = bool(
        final.get("top_symbol") or final.get("candidate_count", 0) > 0
    )
    if not summary_available and dry_run and (
        ground.get("top_symbol") or ground.get("candidate_count", 0) > 0
    ):
        summary_available = True
    tier = classify_telegram_tier(
        final=final,
        suspect_reasons=suspect_reasons,
        log_flags=log_flags,
        quarantined=quarantined,
        summary_available=summary_available,
        dry_run=dry_run,
        scan_integrity_failed=scan_integrity_failed,
    )
    trust_credit = compute_trust_credit(
        dry_run=dry_run,
        rehearsal=rehearsal,
        tier=tier,
        final=final,
        suspect_reasons=suspect_reasons,
        scan_integrity_failed=scan_integrity_failed,
    )
    budget_routes = [
        str((m.get("grid_meta") or {}).get("budget_route") or "")
        for m in metas
    ]
    budget_route = next((b for b in budget_routes if b), "")

    trace = {
        "trade_date": trade_date.isoformat(),
        "dry_run": dry_run,
        "run_mode": "dry_run" if dry_run else "live",
        "log_source": log_source,
        "rehearsal": rehearsal,
        "trust_credit": trust_credit,
        "budget_route": budget_route,
        "generated_at": dt.datetime.now(EST).isoformat(),
        "trace_id": trace_id,
        "trace_path": str(trace_path),
        "telegram_tier": tier,
        "suspect_reasons": suspect_reasons,
        "log_flags": log_flags,
        "log_paths": [str(p) for p in log_paths],
        "log_line_count": len(lines),
        "log_ground_truth": ground,
        "audit": audit,
        "final": final,
        "scan_integrity_failed": scan_integrity_failed,
        "quarantined": quarantined,
        "quarantine_reason": quarantine_reason,
        "inconsistent_triple_vote": inconsistent,
    }

    atomic_write_json(str(trace_path), trace)
    logger.info("trace written %s", trace_path)

    if quarantined:
        qpath = TRACE_DIR / "quarantine" / trace_path.name
        qpath.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(str(qpath), trace)
        logger.warning("quarantined — sending red Telegram (%s)", quarantine_reason)

    tier_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(tier, "⚪")
    try:
        from premarket_ab_scoring import compute_dual_leaderboard
        from premarket_verdict_bootstrap import dual_verdict_report

        premarket_ab["dual_leaderboard"] = compute_dual_leaderboard()
        premarket_ab["verdict_bootstrap"] = dual_verdict_report()
        from premarket_ab_scoring import append_transition_log_info_gap

        append_transition_log_info_gap(premarket_ab["dual_leaderboard"])
    except Exception as exc:
        logger.debug("dual leaderboard skipped: %s", exc)
    ab_text = format_premarket_ab_brief_text(premarket_ab)
    deepseek_text = format_deepseek_performance_text(deepseek_performance)
    msg = format_telegram(
        final,
        trade_date=trade_date,
        dry_run=dry_run,
        trace_id=trace_id,
        trace_rel=trace_rel,
        tier=tier,
        suspect_reasons=suspect_reasons,
        log_flags=log_flags,
        quarantined=quarantined,
        scan_integrity_failed=scan_integrity_failed,
    )
    brief_body = msg
    compile_meta: dict[str, Any] = {}
    from postmarket_fact_pack import build_fact_pack

    fact_pack = build_fact_pack(
        dkey,
        ground=ground,
        premarket_ab=premarket_ab,
        deepseek_performance=deepseek_performance,
    )
    trace["fact_pack"] = fact_pack
    compiled = None
    if not quarantined:
        journal = build_postmarket_journal(
            trade_date,
            ground,
            trace,
            msg,
            premarket_ab=premarket_ab,
            deepseek_performance=deepseek_performance,
        )
        compiled, raw_compile, compile_meta = compile_postmarket_review(journal)
        trace["grid_compile"] = {
            "raw_excerpt": (raw_compile or "")[:2000],
            "meta": compile_meta,
            "compiled": bool(compiled),
        }
        trace["premarket_ab"] = premarket_ab
        trace["deepseek_performance"] = deepseek_performance
        atomic_write_json(str(trace_path), trace)
        if compiled:
            brief_body = compiled
        elif raw_compile and not str(raw_compile).strip().startswith("{"):
            brief_body = f"{msg}\n\n—\n编译漂移已隔离（见 deny 事件）"
        else:
            from postmarket_fact_pack import fallback_brief_body

            brief_body = fallback_brief_body(fact_pack, final=final)
    if final.get("top_symbol") and not quarantined:
        notify_msg = format_notify_message(
            final,
            trade_date=trade_date,
            compiled=compiled or (
                brief_body if brief_body and not str(brief_body).strip().startswith("{") else None
            ),
            ab_text=ab_text,
            deepseek_text=deepseek_text,
        )
    else:
        notify_msg = msg
    send_notification(notify_msg)
    try:
        from postmarket_review_guard import audit_review_text

        brief_body, fact_audits = audit_review_text(brief_body, fact_pack=fact_pack)
        if fact_audits:
            trace["fact_gap_audits"] = fact_audits
            atomic_write_json(str(trace_path), trace)
    except Exception as exc:
        logger.debug("review guard skipped: %s", exc)
    try:
        from tactical_memo import generate_memo_from_signals

        signals = (fact_pack or {}).get("signals") or []
        kills = (fact_pack or {}).get("filter_kill_counts") or {}
        generate_memo_from_signals("grid", dkey, signals=signals, filter_kills=kills)
        generate_memo_from_signals("sonnet", dkey, signals=signals, filter_kills=kills)
    except Exception as exc:
        logger.debug("tactical memo skipped: %s", exc)
    from caliber_lock import caliber_proof_status

    caliber_proof = caliber_proof_status()
    emit_brief(
        trade_date=dkey,
        title=f"{tier_emoji} 盘后摘要 · {dkey}",
        body=brief_body,
        items=(
            brief_items_from_final(final, trade_date=dkey)
            + _paper_brief_items()
            + premarket_ab_brief_items(premarket_ab)
            + deepseek_performance_brief_items(deepseek_performance)
        ),
        tier=tier,
        trace_id=trace_id,
        trace_file=trace_rel,
        trust_credit=trust_credit,
        rehearsal=rehearsal,
        run_mode=trace["run_mode"],
        budget_route=budget_route,
        premarket_ab=premarket_ab,
        fact_pack=fact_pack,
        deepseek_performance=deepseek_performance,
        caliber_proof=caliber_proof,
        dry_run=dry_run,
    )
    logger.info("notification sent tier=%s trust_credit=%s (telegram/pushover per NOTIFY_CHANNEL)", tier, trust_credit)

    try:
        from premarket_ab_journal import reconcile_chain

        reconcile_chain("grid", dkey)
        reconcile_chain("sonnet", dkey)
    except Exception as exc:
        logger.debug("premarket A/B reconcile skipped: %s", exc)

    state = load_state()
    completed = state.setdefault("completed_dates", [])
    if trade_date.isoformat() not in completed:
        completed.append(trade_date.isoformat())
    if dry_run:
        record_dry_run_day(state, trade_date)
    if trust_credit:
        credited = state.setdefault("trust_credit_dates", [])
        if trade_date.isoformat() not in credited:
            credited.append(trade_date.isoformat())
    save_state(state)
    _grid_emit(
        "heartbeat",
        daemon="post_market",
        trade_date=trade_date.isoformat(),
        trace_id=trace_id,
        trust_credit=trust_credit,
        rehearsal=rehearsal,
        tier=tier,
    )
    return trace


def build_postmarket_journal(
    trade_date: dt.date,
    ground: dict[str, Any],
    trace: dict[str, Any],
    index_msg: str,
    *,
    premarket_ab: dict[str, Any] | None = None,
    deepseek_performance: dict[str, Any] | None = None,
) -> str:
    rows = ground.get("parsed_score_rows") or []
    tops = ", ".join(f"{s}({sc:.1f})" for s, sc in rows[:8]) or "none"
    flags = ", ".join(trace.get("final", {}).get("anomaly_flags") or []) or "none"
    ab_block = ""
    if premarket_ab and (premarket_ab.get("grid_n") or premarket_ab.get("sonnet_n")):
        ab_block = (
            f"\nPremarket A/B (report-only, chains independent):\n"
            f"GRID items={premarket_ab.get('grid_n')} aligned={premarket_ab.get('aligned_n')} "
            f"divergence={premarket_ab.get('divergence_n')}\n"
            f"SONNET items={premarket_ab.get('sonnet_n')}\n"
            f"{format_premarket_ab_brief_text(premarket_ab)}\n"
        )
    ds_block = ""
    if deepseek_performance and format_deepseek_performance_text(deepseek_performance):
        ds_block = (
            f"\nDeepSeek performance (report-only, vs Sonnet where available):\n"
            f"{format_deepseek_performance_text(deepseek_performance)}\n"
        )
    from postmarket_fact_pack import build_fact_pack, format_fact_pack_for_journal

    fact_pack = build_fact_pack(
        trade_date.isoformat(),
        ground=ground,
        premarket_ab=premarket_ab,
        deepseek_performance=deepseek_performance,
    )
    fact_block = format_fact_pack_for_journal(fact_pack)
    return (
        f"Trade date: {trade_date.isoformat()}\n"
        f"Tier: {trace.get('telegram_tier')} trust_credit={trace.get('trust_credit')}\n"
        f"Top candidates: {tops}\n"
        f"Flags: {flags}\n"
        f"Scan integrity failed: {trace.get('scan_integrity_failed')}\n"
        f"{fact_block}\n"
        f"{_paper_journal_block()}\n"
        f"{ab_block}"
        f"{ds_block}"
        f"Telegram index (do not restate numbers verbatim):\n{index_msg}\n"
        "请输出今日对错各一条 + 次日关注1-3条（五字段格式）。"
        "禁止编造胜率/平仓统计（fact pack 已声明零平仓）。"
        "若盘前 A/B 有分歧标的，复盘里简要点评（不合并两链胜率）。"
        "若有 DeepSeek 表现数据，简要对比 off-pool / 盘前质量（不触发 learning）。"
    )


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.strip().split(":")
    return int(h), int(m)


def scheduler_loop(*, dry_run: bool) -> None:
    hour, minute = _parse_hhmm(POST_MARKET_TIME)
    logger.info(
        "post-market summary daemon v1 | dry_run=%s | fire at %02d:%02d EST",
        dry_run,
        hour,
        minute,
    )
    while True:
        now = dt.datetime.now(EST)
        if dry_run:
            state = load_state()
            if len(state.get("dry_run_days_log") or []) >= DRY_RUN_MAX_DAYS:
                logger.info("dry-run complete (%d trading days)", DRY_RUN_MAX_DAYS)
                break
        if now.weekday() < 5 and is_trading_day(now.date()):
            dkey = now.date().isoformat()
            state = load_state()
            if dkey not in state.get("completed_dates", []) and slot_due(now, hour, minute):
                run_for_date(now.date(), dry_run=dry_run)
                time.sleep(70)
        time.sleep(30)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    ap = argparse.ArgumentParser(description="Aether post-market summary daemon v1")
    ap.add_argument("--once", action="store_true", help="Run one summary now (ignore schedule)")
    ap.add_argument("--date", help="Trade date YYYY-MM-DD (default: today EST)")
    ap.add_argument("--dry-run", action="store_true", help="Prefix [DRY-RUN]; count toward 5-day acceptance")
    ap.add_argument("--force", action="store_true", help="Run even if already completed for date")
    ap.add_argument("--loop", action="store_true", help="Schedule daily after POST_MARKET_SUMMARY_TIME")
    ap.add_argument("--test", action="store_true", help="Test mode: state writes go to state_test/ only")
    ap.add_argument(
        "--production",
        action="store_true",
        help="Manual --force writes production state (default: test mode for --force)",
    )
    args = ap.parse_args()

    manual_once = bool(args.once or args.date or (args.force and not args.loop))
    test_mode = bool(
        args.test or os.getenv("AETHER_TEST", "").lower() in ("1", "true", "yes")
    )
    if manual_once and args.force and not args.production:
        test_mode = True
    if args.production and not args.force:
        ap.error("--production requires --force for manual runs")
    set_test_mode(test_mode)
    if test_mode:
        logger.info(
            "TEST MODE: state writes -> %s (production state read-only)",
            STATE_TEST_DIR,
        )

    dry_run = args.dry_run or os.getenv("POST_MARKET_SUMMARY_DRY_RUN", "").lower() in ("1", "true", "yes")

    if args.date:
        trade_date = dt.date.fromisoformat(args.date)
    else:
        trade_date = dt.datetime.now(EST).date()

    dry_run = resolve_effective_dry_run(cli_dry_run=dry_run)

    if args.once or not args.loop:
        state = load_state()
        if not args.force and trade_date.isoformat() in state.get("completed_dates", []):
            logger.info("already completed for %s (use --force)", trade_date)
            return
        try:
            trace = run_for_date(trade_date, dry_run=dry_run, force=args.force)
        except (RuntimeError, FileNotFoundError) as exc:
            logger.warning("%s", exc)
            return
        print(json.dumps(trace["final"], ensure_ascii=False, indent=2))
        return

    scheduler_loop(dry_run=dry_run)


if __name__ == "__main__":
    main()
