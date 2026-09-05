#!/usr/bin/env python3
"""Premarket Sonnet compile — 06:30 EST via CC CLI, report-only, isolated from Grid."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from aether_shared import EST, atomic_write_json  # noqa: E402
from aether_grid_emit import emit_premarket_sonnet  # noqa: E402
from grid_compile_hygiene import detect_field_drift, parse_premarket_items, quarantine_drift  # noqa: E402
from premarket_ab_isolation import assert_sonnet_prompt_isolated, assert_sonnet_no_retrieval_tools  # noqa: E402
from premarket_ab_journal import append_premarket_journal  # noqa: E402
from premarket_pool_context import build_pool_premarket_context, filter_items_to_pool  # noqa: E402
from daemon_schedule import parse_hhmm, slot_due  # noqa: E402

try:
    from sonnet_egress_client import PREMARKET_SONNET_SYSTEM  # noqa: E402
except ImportError:
    PREMARKET_SONNET_SYSTEM = """你是 Aether Nexus 盘前 Pool 编译节点（云端 Sonnet lane）。只输出候选列表，不输出交易指令。
必须严格使用以下五字段格式，每条一行块，输出 3-5 个候选，标的必须来自用户给出的 pool 宇宙：

标的：SYMBOL|方向：多/空/观察|为什么今天：（一句）|风险：（一句）|置信：[高置信/试探性/观察]

规则：数据不全时宁可少给不可错给；缺核心因子的标的只给[观察]不给方向。"""

try:
    from aether_dryrun import is_trading_day
except Exception:
    def is_trading_day(d: dt.date | None = None) -> bool:
        d = d or dt.datetime.now(EST).date()
        return d.weekday() < 5

logger = logging.getLogger("PremarketSonnet")
AB_SEALED = True  # _sealed/ab_2026-07/ · 2026-07-20 中止
PREMARKET_SONNET_TIME = os.getenv("PREMARKET_SONNET_TIME", "06:40")
CLAUDE_BIN = os.getenv(
    "CLAUDE_BIN",
    str(REPO_ROOT / "aster_grid_v5" / ".tools" / "node_modules" / ".bin" / "claude"),
)
CLAUDE_TIMEOUT = int(os.getenv("PREMARKET_SONNET_CLI_TIMEOUT", "180"))
STATE_PATH = BASE_DIR / "premarket_sonnet_state.json"
STATE_TEST_DIR = BASE_DIR / "state_test"
DRIFT_TRACE_DIR = os.getenv(
    "GRID_DRIFT_TRACE_DIR",
    str(BASE_DIR.parent / "grid-sovereign-runtime" / "traces" / "drift"),
)
_test_mode = False


def set_test_mode(enabled: bool) -> None:
    global _test_mode
    _test_mode = bool(enabled)


def _state_path() -> Path:
    if _test_mode:
        return STATE_TEST_DIR / "premarket_sonnet_state.json"
    return STATE_PATH


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def compile_premarket_sonnet_cli(user_prompt: str) -> tuple[list[dict[str, Any]] | None, str, dict[str, Any]]:
    """CC CLI primary — same auth path as offpool (no :8503 API key)."""
    assert_sonnet_prompt_isolated(user_prompt)
    assert_sonnet_no_retrieval_tools(system_prompt=PREMARKET_SONNET_SYSTEM)
    meta: dict[str, Any] = {"route": "cc_cli", "cli_model": os.getenv("PREMARKET_SONNET_CLI_MODEL", "claude-sonnet-4-6")}
    if os.environ.get("CC_CLI_EXECUTION_FROZEN", "1") not in ("0", "false", "False"):
        logger.info("CC_CLI_EXECUTION_FROZEN=1 — claude -p read-only capture only")
    if not shutil.which(CLAUDE_BIN) and not Path(CLAUDE_BIN).is_file():
        meta["error"] = "claude_missing"
        return None, "", meta
    prompt = f"{PREMARKET_SONNET_SYSTEM}\n\n{user_prompt}"
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--model", meta["cli_model"], "--output-format", "json"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        meta["error"] = "timeout"
        return None, "", meta
    if proc.returncode != 0:
        meta["error"] = f"exit_{proc.returncode}"
        meta["stderr"] = (proc.stderr or "")[:400]
        return None, "", meta
    try:
        envelope = json.loads(proc.stdout)
        meta["duration_ms"] = envelope.get("duration_ms")
        meta["cost_usd"] = envelope.get("total_cost_usd")
        text = str(envelope.get("result") or envelope.get("content") or "")
    except json.JSONDecodeError:
        text = proc.stdout or ""
    if detect_field_drift(text):
        quarantine_drift(
            text,
            context="premarket_sonnet_cli",
            trace_dir=Path(DRIFT_TRACE_DIR),
            raw_prompt=user_prompt,
        )
        return None, text, meta
    items = parse_premarket_items(text)
    if items:
        items = filter_items_to_pool(items)
    return items, text, meta


def compile_premarket_sonnet(user_prompt: str) -> tuple[list[dict[str, Any]] | None, str, dict[str, Any]]:
    return compile_premarket_sonnet_cli(user_prompt)


def run_for_date(trade_date: dt.date, *, force: bool = False) -> dict[str, Any]:
    if AB_SEALED and not _test_mode and not os.getenv("AETHER_SONNET_LANE_UNLOCK"):
        logger.error("premarket sonnet lane sealed since 2026-07-20 — refuse run (set AETHER_SONNET_LANE_UNLOCK=1 to override)")
        return {"skipped": True, "sealed": True, "trade_date": trade_date.isoformat()}
    state = _read_json(_state_path(), {"completed_dates": []})
    dkey = trade_date.isoformat()
    if not force and dkey in (state.get("completed_dates") or []):
        logger.info("premarket sonnet already done for %s", dkey)
        return {"skipped": True, "trade_date": dkey}

    user_prompt = build_pool_premarket_context(trade_date)
    from tactical_memo import build_memo_prompt_tail

    user_prompt += build_memo_prompt_tail("sonnet", trade_date.isoformat())
    items, raw, meta = compile_premarket_sonnet(user_prompt)
    result: dict[str, Any] = {
        "trade_date": dkey,
        "generated_at": dt.datetime.now(EST).isoformat(),
        "items": items,
        "raw_excerpt": (raw or "")[:2000],
        "meta": meta,
        "chain": "sonnet",
        "test_mode": _test_mode,
    }
    if items:
        emit_premarket_sonnet(
            trade_date=dkey,
            items=items,
            raw=raw,
            generated_at=result["generated_at"],
        )
        append_premarket_journal(chain="sonnet", trade_date=dkey, items=items, meta=meta)
        logger.info("premarket sonnet emitted %d items route=%s", len(items), meta.get("route"))
        if not _test_mode:
            completed = state.setdefault("completed_dates", [])
            if dkey not in completed:
                completed.append(dkey)
            atomic_write_json(str(_state_path()), state)
    else:
        logger.warning("premarket sonnet produced no store items route=%s err=%s", meta.get("route"), meta.get("error"))
    return result


def scheduler_loop() -> None:
    hour, minute = parse_hhmm(PREMARKET_SONNET_TIME)
    logger.info("premarket sonnet daemon | fire at %02d:%02d EST", hour, minute)
    while True:
        now = dt.datetime.now(EST)
        if now.weekday() < 5 and is_trading_day(now.date()):
            dkey = now.date().isoformat()
            state = _read_json(_state_path(), {"completed_dates": []})
            if dkey not in (state.get("completed_dates") or []) and slot_due(now, hour, minute):
                run_for_date(now.date(), force=False)
                time.sleep(65)
        time.sleep(20)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    ap = argparse.ArgumentParser(description="Aether premarket Sonnet compile via CC CLI (report-only)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--cli-fallback", action="store_true", help=argparse.SUPPRESS)  # compat alias
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--test", action="store_true", help="No production state writes")
    args = ap.parse_args()
    set_test_mode(bool(args.test or os.getenv("AETHER_TEST", "").lower() in ("1", "true", "yes")))
    if _test_mode:
        STATE_TEST_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("TEST MODE: state -> %s", STATE_TEST_DIR)

    trade_date = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(EST).date()
    if args.loop and not args.once:
        scheduler_loop()
        return
    out = run_for_date(trade_date, force=args.force)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
