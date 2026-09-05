#!/usr/bin/env python3
"""Off-pool daily top3 — dual-lane A/B (Sonnet CC CLI + DeepSeek V4 Ollama cloud).

Report-only → emit aether_offpool. No Anthropic API / :8503.
CC_CLI_EXECUTION_FROZEN=1 (claude -p only, no writes/exec).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from aether_shared import EST, atomic_write_json  # noqa: E402
from daemon_schedule import parse_hhmm, slot_due  # noqa: E402
from aether_grid_emit import emit_offpool  # noqa: E402
from pool_config import pool_symbols_set  # noqa: E402
from offpool_ab_stats import (  # noqa: E402
    assert_offpool_constitution,
    grounded_emit_items,
    load_offpool_candidates,
    near_miss_symbols_from_rejection_log,
    score_fabrication,
    store_stats_from_emit,
)

try:
    from aether_dryrun import is_trading_day
except Exception:
    def is_trading_day(d: dt.date | None = None) -> bool:
        d = d or dt.datetime.now(EST).date()
        return d.weekday() < 5

logger = logging.getLogger("AetherOffpool")

OFFPOOL_TIME = os.getenv("OFFPOOL_TIME", "10:50")
CLAUDE_BIN = os.getenv(
    "CLAUDE_BIN",
    str(REPO_ROOT / "aster_grid_v5" / ".tools" / "node_modules" / ".bin" / "claude"),
)
CLAUDE_TIMEOUT = int(os.getenv("OFFPOOL_CLI_TIMEOUT", "180"))
DRYRUN_STATE = BASE_DIR / "dryrun_state"
TRACE_DIR = REPO_ROOT / "grid-sovereign-runtime" / "traces" / "daemon"
PROMPT_DUMP_DIR = TRACE_DIR / "offpool_prompts"
STATE_PATH = BASE_DIR / "offpool_state.json"
STATE_TEST_DIR = BASE_DIR / "state_test"
_test_mode = False

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)


from offpool_lane_config import OffpoolLane, default_offpool_lanes  # noqa: E402

OFFPOOL_LANES = default_offpool_lanes()
OFFPOOL_SCHEDULE_TZ = os.getenv("OFFPOOL_SCHEDULE_TZ", "eastern").strip().lower()
DEEPSEEK_TIMEOUT = float(os.getenv("OFFPOOL_DEEPSEEK_TIMEOUT", "300"))


def set_test_mode(enabled: bool) -> None:
    global _test_mode
    _test_mode = bool(enabled)


def _state_path() -> Path:
    return STATE_TEST_DIR / "offpool_state.json" if _test_mode else STATE_PATH


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _normalize_state(raw: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """Per-date per-lane completion map."""
    completed: dict[str, dict[str, bool]] = {}
    if isinstance(raw.get("completed"), dict):
        for dkey, lanes in raw["completed"].items():
            if isinstance(lanes, dict):
                completed[str(dkey)] = {str(k): bool(v) for k, v in lanes.items()}
    return completed


def _state_write(completed: dict[str, dict[str, bool]]) -> None:
    atomic_write_json(str(_state_path()), {"completed": completed, "lanes": [l.lane for l in OFFPOOL_LANES]})


def _pool_symbols() -> set[str]:
    return pool_symbols_set()


def _latest_rejection_log() -> Path | None:
    rej_dir = BASE_DIR / "logs" / "rejections"
    if not rej_dir.is_dir():
        return None
    files = sorted(rej_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _near_miss_symbols() -> set[str]:
    pool_syms = _pool_symbols()
    rej = _latest_rejection_log()
    if rej is None:
        return set()
    return near_miss_symbols_from_rejection_log(rej, pool_syms)


def _offpool_candidates() -> list[dict[str, Any]]:
    pool_syms = _pool_symbols()
    rej = _latest_rejection_log()
    if rej is None:
        return []
    return load_offpool_candidates(rej, pool_syms)


def build_offpool_context(trade_date: dt.date) -> str:
    """Whitelist-only prompt — no dryrun tail, rejection raw, scan, or perilla."""
    pool_syms = sorted(_pool_symbols())
    candidates = _offpool_candidates()
    lines: list[str] = [
        f"Trade date: {trade_date.isoformat()}",
        "Off-pool lane — pick ONLY from the candidate whitelist below (report-only).",
        f"Pool exclusion — do NOT duplicate ({len(pool_syms)}): {', '.join(pool_syms) or '(empty)'}",
        "",
        f"Off-pool candidate whitelist ({len(candidates)} symbols, quant-derived):",
    ]
    if candidates:
        for row in candidates:
            lines.append(
                f"- {row['sym']} score={row['score']} killed={row.get('kill_rule') or '?'}"
            )
    else:
        lines.append("- (empty — return {\"items\":[]} )")
    lines.append(
        "\nReturn ONLY valid JSON (no markdown prose):\n"
        '{"items":[{"sym":"TICKER","value":"多·[试探性]","note":"why today + risk","dir":1}]}\n'
        "Rules: up to 3 items; ONLY symbols from the whitelist above; "
        "E-line constitution: single-leg call, long-only — NO bearish/short/neutral-wait tools; "
        "if conviction insufficient return {\"items\":[]}; "
        "dir MUST be 1 for every item; "
        'value must combine direction and confidence [高置信|试探性]; '
        "report-only, no trade instructions; do not fabricate symbols outside the whitelist."
    )
    return "\n".join(lines)


def _extract_json_blob(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    m = _JSON_BLOCK.search(text)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _normalize_item(row: dict) -> dict | None:
    sym = str(row.get("sym") or row.get("symbol") or "").strip().upper()
    if not sym or sym == "—":
        return None
    note = str(row.get("note") or row.get("why") or "").strip()
    value = str(row.get("value") or row.get("judgment") or "").strip()
    if not value:
        d = row.get("dir")
        conf = row.get("confidence") or row.get("conf") or "试探性"
        direction = "多" if d == 1 or d == "1" else "空" if d == -1 or d == "-1" else "中性"
        value = f"{direction}·[{conf}]"
    dir_raw = row.get("dir")
    if dir_raw in (1, -1, 0):
        dir_i = int(dir_raw)
    elif "多" in value or "bull" in value.lower():
        dir_i = 1
    elif "空" in value or "bear" in value.lower():
        dir_i = -1
    else:
        dir_i = 0
    return {"sym": sym, "value": value, "note": note, "dir": dir_i}


def parse_offpool_items(raw: str) -> list[dict]:
    obj = _extract_json_blob(raw)
    if not obj:
        return []
    rows = obj.get("items") or obj.get("candidates") or []
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        norm = _normalize_item(row)
        if norm and norm["sym"] not in seen:
            seen.add(norm["sym"])
            out.append(norm)
        if len(out) >= 3:
            break
    return out


def _schedule_now() -> dt.datetime:
    if OFFPOOL_SCHEDULE_TZ in ("est", "eastern", "us/eastern"):
        return dt.datetime.now(EST)
    return dt.datetime.now().astimezone()


def claude_capture(prompt: str, lane: OffpoolLane) -> tuple[str | None, str, dict[str, Any]]:
    meta: dict[str, Any] = {
        "lane": lane.lane,
        "backend": lane.backend,
        "cli_model": lane.cli_model,
        "model": lane.model,
        "label": lane.label,
        "resolved_models": [],
        "cost_usd": None,
        "duration_ms": None,
        "error": None,
    }
    if os.environ.get("CC_CLI_EXECUTION_FROZEN", "1") not in ("0", "false", "False"):
        logger.info("CC_CLI_EXECUTION_FROZEN=1 — claude -p read-only capture only")
    if not shutil.which(CLAUDE_BIN) and not Path(CLAUDE_BIN).is_file():
        logger.error("claude binary missing: %s", CLAUDE_BIN)
        meta["error"] = "claude_missing"
        return None, lane.lane, meta
    try:
        proc = subprocess.run(
            [
                CLAUDE_BIN,
                "-p",
                prompt,
                "--model",
                lane.cli_model,
                "--output-format",
                "json",
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error("claude timeout lane=%s after %ss", lane.lane, CLAUDE_TIMEOUT)
        meta["error"] = "timeout"
        return None, lane.lane, meta
    if proc.returncode != 0:
        logger.error("claude exit lane=%s code=%s stderr=%s", lane.lane, proc.returncode, (proc.stderr or "")[:400])
        meta["error"] = f"exit_{proc.returncode}"
        return None, lane.lane, meta
    try:
        envelope = json.loads(proc.stdout)
        meta["duration_ms"] = envelope.get("duration_ms")
        meta["cost_usd"] = envelope.get("total_cost_usd")
        meta["resolved_models"] = list((envelope.get("modelUsage") or {}).keys())
        text = (
            envelope.get("result")
            or envelope.get("text")
            or envelope.get("content")
            or proc.stdout
        )
        return str(text).strip(), lane.lane, meta
    except json.JSONDecodeError:
        meta["error"] = "bad_envelope"
        return proc.stdout.strip(), lane.lane, meta


def deepseek_capture(prompt: str, lane: OffpoolLane) -> tuple[str | None, str, dict[str, Any]]:
    from offpool_deepseek_capture import capture_sync  # noqa: WPS433

    meta: dict[str, Any] = {
        "lane": lane.lane,
        "backend": lane.backend,
        "cli_model": "",
        "model": lane.model,
        "label": lane.label,
        "resolved_models": [lane.model],
        "cost_usd": None,
        "duration_ms": None,
        "error": None,
    }
    text, cloud_meta = capture_sync(prompt=prompt, model=lane.model, timeout=DEEPSEEK_TIMEOUT)
    meta.update({k: v for k, v in cloud_meta.items() if k in meta or k in ("thinking_hash", "endpoint")})
    if cloud_meta.get("error"):
        meta["error"] = cloud_meta["error"]
    if text:
        meta["resolved_models"] = cloud_meta.get("resolved_models") or [lane.model]
    return text, lane.lane, meta


def model_capture(prompt: str, lane: OffpoolLane) -> tuple[str | None, str, dict[str, Any]]:
    if lane.backend == "ollama_cloud":
        return deepseek_capture(prompt, lane)
    if lane.backend == "cc_cli":
        return claude_capture(prompt, lane)
    meta = {"lane": lane.lane, "backend": lane.backend, "error": f"unknown_backend:{lane.backend}"}
    return None, lane.lane, meta


def run_lane(
    trade_date: dt.date,
    lane: OffpoolLane,
    prompt: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    dkey = trade_date.isoformat()
    raw, lane_key, capture_meta = model_capture(prompt, lane)
    raw_items = parse_offpool_items(raw or "")
    pool_syms = _pool_symbols()
    near_miss = _near_miss_symbols()
    # H10: ground against the same S&P500-filtered candidate whitelist the model
    # was prompted with, so a non-whitelist symbol cannot pass grounding just
    # because it appears in the broader near-miss rejection log.
    candidate_syms = {str(c.get("sym") or "").upper() for c in _offpool_candidates()}
    raw_items, constitution_dropped = assert_offpool_constitution(raw_items)
    emit_items, dropped_syms = grounded_emit_items(
        raw_items, near_miss_syms=near_miss, pool_syms=pool_syms, candidate_syms=candidate_syms or None
    )
    audit = score_fabrication(raw_items, near_miss_syms=near_miss, near_miss_count=len(near_miss))
    audit["dropped_syms"] = dropped_syms
    audit["constitution_dropped"] = constitution_dropped
    audit["raw_item_count"] = len(raw_items)
    audit["emit_item_count"] = len(emit_items)

    stats = store_stats_from_emit(
        emit_items,
        near_miss_count=len(near_miss),
        parse_ok=bool(raw_items) or (raw and _extract_json_blob(raw) is not None),
        **{k: v for k, v in capture_meta.items() if k not in ("error",)},
    )
    stats["backend"] = lane.backend
    stats["in_pool_count"] = sum(1 for s in dropped_syms if s in pool_syms)

    if audit.get("fabricated_count") or audit.get("hard_pad") or dropped_syms:
        logger.warning(
            "offpool audit lane=%s raw=%d emit=%d fabricated=%s hard_pad=%s dropped=%s syms=%s",
            lane.lane,
            len(raw_items),
            len(emit_items),
            audit.get("fabricated_count"),
            audit.get("hard_pad"),
            len(dropped_syms),
            dropped_syms,
        )

    result: dict[str, Any] = {
        "trade_date": dkey,
        "generated_at": dt.datetime.now(EST).isoformat(),
        "lane": lane.lane,
        "backend": lane.backend,
        "model": lane.model,
        "label": lane.label,
        "cli_model": lane.cli_model,
        "resolved_models": capture_meta.get("resolved_models") or [],
        "items": emit_items,
        "items_raw": raw_items,
        "stats": stats,
        "audit": audit,
        "prompt_dump": prompt,
        "raw_excerpt": (raw or "")[:2000],
        "test_mode": _test_mode,
    }
    if capture_meta.get("error"):
        result["error"] = capture_meta["error"]

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    PROMPT_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    trace_path = TRACE_DIR / f"offpool_{lane.lane}_{dkey}.json"
    prompt_path = PROMPT_DUMP_DIR / f"offpool_{lane.lane}_{dkey}.prompt.txt"
    atomic_write_json(str(trace_path), result)
    prompt_path.write_text(prompt, encoding="utf-8")

    if not _test_mode:
        ok = emit_offpool(
            trade_date=dkey,
            items=emit_items,
            lane=lane.lane,
            model=lane.lane,
            label=lane.label,
            cli_model=lane.cli_model,
            resolved_models=capture_meta.get("resolved_models") or [],
            stats=stats,
            raw=raw or "",
        )
        result["store_emitted"] = ok
        logger.info(
            "offpool lane=%s emit=%d raw=%d store=%s resolved=%s",
            lane.lane,
            len(emit_items),
            len(raw_items),
            ok,
            capture_meta.get("resolved_models"),
        )
    elif emit_items:
        logger.info("TEST MODE lane=%s would emit %d items (raw %d)", lane.lane, len(emit_items), len(raw_items))
    elif not raw_items:
        logger.warning("offpool lane=%s parse empty — see %s", lane.lane, trace_path)

    return result


def run_for_date(trade_date: dt.date, *, force: bool = False, lanes: list[OffpoolLane] | None = None) -> dict[str, Any]:
    lanes = lanes or OFFPOOL_LANES
    dkey = trade_date.isoformat()
    state_raw = _read_json(_state_path(), {})
    completed = _normalize_state(state_raw if isinstance(state_raw, dict) else {})
    day_done = completed.get(dkey) or {}

    pending = [ln for ln in lanes if force or not day_done.get(ln.lane)]
    if not pending:
        logger.info("offpool already done for %s (all lanes)", dkey)
        return {"skipped": True, "trade_date": dkey, "lanes": [l.lane for l in lanes]}

    prompt = build_offpool_context(trade_date)
    results: dict[str, Any] = {"trade_date": dkey, "lanes": {}}

    # Sequential — Sonnet (cc_cli) first, DeepSeek after; same prompt, isolated lanes.
    lane_order = {ln.lane: idx for idx, ln in enumerate(lanes)}
    pending.sort(key=lambda ln: lane_order.get(ln.lane, 999))
    for ln in pending:
        try:
            results["lanes"][ln.lane] = run_lane(trade_date, ln, prompt, force=force)
        except Exception as exc:
            logger.exception("offpool lane=%s failed: %s", ln.lane, exc)
            results["lanes"][ln.lane] = {"lane": ln.lane, "error": str(exc)}

    if not _test_mode:
        completed.setdefault(dkey, {})
        for ln in pending:
            lane_result = results["lanes"].get(ln.lane) or {}
            if lane_result.get("error"):
                continue
            # Gate completion on emit success: a lane whose store emit failed must
            # stay pending so the next scheduler tick retries it, instead of being
            # marked done and silently missing from the mobile app.
            if not lane_result.get("store_emitted"):
                logger.error(
                    "offpool lane=%s emit failed — not marking completed (will retry)",
                    ln.lane,
                )
                continue
            completed[dkey][ln.lane] = True
        _state_write(completed)

    return results


def scheduler_loop() -> None:
    hour, minute = parse_hhmm(OFFPOOL_TIME)
    lane_names = ", ".join(f"{l.lane}({l.backend})" for l in OFFPOOL_LANES)
    tz_note = OFFPOOL_SCHEDULE_TZ if OFFPOOL_SCHEDULE_TZ != "local" else "local"
    logger.info(
        "offpool daemon | fire at %02d:%02d %s | lanes (sequential): %s",
        hour,
        minute,
        tz_note,
        lane_names,
    )
    while True:
        now = _schedule_now()
        if now.weekday() < 5 and is_trading_day(now.date()):
            dkey = now.date().isoformat()
            state_raw = _read_json(_state_path(), {})
            completed = _normalize_state(state_raw if isinstance(state_raw, dict) else {})
            day_done = completed.get(dkey) or {}
            if not all(day_done.get(ln.lane) for ln in OFFPOOL_LANES) and slot_due(now, hour, minute):
                run_for_date(now.date(), force=False)
                time.sleep(65)
        time.sleep(20)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    ap = argparse.ArgumentParser(description="Aether off-pool dual-lane capture (Sonnet CC + DeepSeek V4 cloud)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--test", action="store_true", help="No store/state writes")
    ap.add_argument("--lane", help="Run single lane id (e.g. sonnet-4.6)")
    ap.add_argument("--dump-prompt", action="store_true", help="Print whitelist prompt and exit")
    args = ap.parse_args()
    set_test_mode(bool(args.test or os.getenv("AETHER_TEST", "").lower() in ("1", "true", "yes")))
    if _test_mode:
        STATE_TEST_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("TEST MODE")

    lanes = OFFPOOL_LANES
    if args.lane:
        lanes = [ln for ln in OFFPOOL_LANES if ln.lane == args.lane]
        if not lanes:
            raise SystemExit(f"unknown lane: {args.lane}")

    trade_date = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(EST).date()
    if args.dump_prompt:
        prompt = build_offpool_context(trade_date)
        print(prompt)
        return
    if args.loop and not args.once:
        scheduler_loop()
        return
    out = run_for_date(trade_date, force=args.force, lanes=lanes)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
