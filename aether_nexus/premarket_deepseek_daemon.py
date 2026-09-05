#!/usr/bin/env python3
"""Premarket pool compile — DeepSeek V4 Ollama cloud, 2× daily, isolated from Grid/Sonnet."""
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
REPO_ROOT = BASE_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from aether_shared import EST, atomic_write_json  # noqa: E402
from aether_grid_emit import emit_premarket_deepseek  # noqa: E402
from grid_compile_hygiene import detect_field_drift, parse_premarket_items, quarantine_drift  # noqa: E402
from premarket_pool_context import build_pool_premarket_context, filter_items_to_pool  # noqa: E402
from premarket_deepseek_config import PremarketDeepseekWindow, default_premarket_deepseek_windows  # noqa: E402
from daemon_schedule import slot_due  # noqa: E402

try:
    from aether_dryrun import is_trading_day
except Exception:
    def is_trading_day(d: dt.date | None = None) -> bool:
        d = d or dt.datetime.now(EST).date()
        return d.weekday() < 5

logger = logging.getLogger("PremarketDeepseek")

PREMARKET_DEEPSEEK_SYSTEM = """你是 Aether Nexus 盘前 Pool 编译节点（DeepSeek V4 cloud lane · report-only）。
只输出候选列表，不输出交易指令。禁止引用其他 lane（Grid / Sonnet）的输出。
必须严格使用以下五字段格式，每条一行块，输出 3-5 个候选，标的必须来自用户给出的 pool 宇宙：

标的：SYMBOL|方向：多/空/观察|为什么今天：（一句）|风险：（一句）|置信：[高置信/试探性/观察]

规则：数据不全时宁可少给不可错给；缺核心因子的标的只给[观察]不给方向。"""

DEEPSEEK_MODEL = os.getenv(
    "PREMARKET_DEEPSEEK_MODEL",
    os.getenv("OFFPOOL_DEEPSEEK_MODEL", "deepseek-v4-flash:cloud"),
)
DEEPSEEK_TIMEOUT = float(os.getenv("PREMARKET_DEEPSEEK_TIMEOUT", "300"))
SCHEDULE_TZ = os.getenv("PREMARKET_DEEPSEEK_SCHEDULE_TZ", "eastern").strip().lower()
WINDOWS = default_premarket_deepseek_windows()
STATE_PATH = BASE_DIR / "premarket_deepseek_state.json"
STATE_TEST_DIR = BASE_DIR / "state_test"
TRACE_DIR = REPO_ROOT / "grid-sovereign-runtime" / "traces" / "daemon"
DRIFT_TRACE_DIR = os.getenv(
    "GRID_DRIFT_TRACE_DIR",
    str(REPO_ROOT / "grid-sovereign-runtime" / "traces" / "drift"),
)
_test_mode = False


def set_test_mode(enabled: bool) -> None:
    global _test_mode
    _test_mode = bool(enabled)


def _state_path() -> Path:
    return STATE_TEST_DIR / "premarket_deepseek_state.json" if _test_mode else STATE_PATH


def _schedule_now() -> dt.datetime:
    if SCHEDULE_TZ in ("est", "eastern", "us/eastern"):
        return dt.datetime.now(EST)
    return dt.datetime.now().astimezone()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _normalize_state(raw: dict[str, Any]) -> dict[str, dict[str, bool]]:
    completed: dict[str, dict[str, bool]] = {}
    if isinstance(raw.get("completed"), dict):
        for dkey, wins in raw["completed"].items():
            if isinstance(wins, dict):
                completed[str(dkey)] = {str(k): bool(v) for k, v in wins.items()}
    return completed


def _state_write(completed: dict[str, dict[str, bool]]) -> None:
    atomic_write_json(
        str(_state_path()),
        {"completed": completed, "windows": [w.key for w in WINDOWS]},
    )


def assert_deepseek_prompt_isolated(prompt: str) -> None:
    low = (prompt or "").lower()
    for token in (
        "aether_premarket_grid",
        "aether_premarket_sonnet",
        "journal_grid",
        "journal_sonnet",
        "grid lane",
        "sonnet lane",
        "本地·grid",
        "云端·sonnet",
    ):
        if token.lower() in low:
            raise ValueError(f"deepseek premarket isolation violation: contains {token!r}")


def compile_premarket_deepseek(user_prompt: str) -> tuple[list[dict[str, Any]] | None, str, dict[str, Any]]:
    from offpool_deepseek_capture import capture_sync  # noqa: WPS433

    assert_deepseek_prompt_isolated(user_prompt)
    prompt = f"{PREMARKET_DEEPSEEK_SYSTEM}\n\n{user_prompt}"
    text, meta = capture_sync(prompt=prompt, model=DEEPSEEK_MODEL, timeout=DEEPSEEK_TIMEOUT)
    meta = dict(meta)
    meta["route"] = "ollama_cloud"
    meta["lane"] = "deepseek-v4"
    if meta.get("error"):
        return None, text or "", meta
    if detect_field_drift(text or ""):
        quarantine_drift(
            text or "",
            context="premarket_deepseek",
            trace_dir=Path(DRIFT_TRACE_DIR),
            raw_prompt=user_prompt,
        )
        meta["error"] = "field_drift"
        return None, text or "", meta
    items = parse_premarket_items(text or "")
    if items:
        items = filter_items_to_pool(items)
    return items, text or "", meta


def run_for_window(
    trade_date: dt.date,
    window: PremarketDeepseekWindow,
    *,
    force: bool = False,
) -> dict[str, Any]:
    dkey = trade_date.isoformat()
    state_raw = _read_json(_state_path(), {})
    completed = _normalize_state(state_raw if isinstance(state_raw, dict) else {})
    day_done = completed.get(dkey) or {}
    if not force and day_done.get(window.key):
        logger.info("premarket deepseek already done %s window=%s", dkey, window.key)
        return {"skipped": True, "trade_date": dkey, "window": window.key}

    user_prompt = build_pool_premarket_context(trade_date)
    user_prompt += f"\n\n[window={window.key} · {window.label} · local schedule {window.hour:02d}:{window.minute:02d}]"
    items, raw, meta = compile_premarket_deepseek(user_prompt)
    result: dict[str, Any] = {
        "trade_date": dkey,
        "window": window.key,
        "window_label": window.label,
        "generated_at": dt.datetime.now(EST).isoformat(),
        "items": items,
        "raw_excerpt": (raw or "")[:2000],
        "meta": meta,
        "chain": "deepseek-v4",
        "test_mode": _test_mode,
    }

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    trace_path = TRACE_DIR / f"premarket_deepseek_{window.key}_{dkey}.json"
    atomic_write_json(str(trace_path), result)

    if items and not _test_mode:
        ok = emit_premarket_deepseek(
            trade_date=dkey,
            window=window.key,
            window_label=window.label,
            items=items,
            raw=raw,
            generated_at=result["generated_at"],
            meta=meta,
        )
        result["store_emitted"] = ok
        # Gate completion on emit success: a window whose store emit failed must
        # stay pending so the next scheduler tick retries it, instead of being
        # marked done and silently dropped from the mobile app.
        if ok:
            completed.setdefault(dkey, {})[window.key] = True
            _state_write(completed)
        else:
            logger.error(
                "premarket deepseek emit FAILED window=%s — not marking completed (will retry)",
                window.key,
            )
        logger.info(
            "premarket deepseek emitted %d items window=%s store=%s",
            len(items),
            window.key,
            ok,
        )
    elif not items:
        logger.warning(
            "premarket deepseek empty window=%s err=%s",
            window.key,
            meta.get("error"),
        )
    return result


def run_for_date(
    trade_date: dt.date,
    *,
    force: bool = False,
    windows: list[PremarketDeepseekWindow] | None = None,
) -> dict[str, Any]:
    wins = windows or WINDOWS
    out: dict[str, Any] = {"trade_date": trade_date.isoformat(), "windows": {}}
    for win in wins:
        out["windows"][win.key] = run_for_window(trade_date, win, force=force)
    return out


def scheduler_loop() -> None:
    win_desc = ", ".join(f"{w.key}@{w.hour:02d}:{w.minute:02d}" for w in WINDOWS)
    tz_note = SCHEDULE_TZ if SCHEDULE_TZ != "local" else "local"
    logger.info("premarket deepseek daemon | %s | windows: %s", tz_note, win_desc)
    while True:
        now = _schedule_now()
        if now.weekday() < 5 and is_trading_day(now.date()):
            dkey = now.date().isoformat()
            state_raw = _read_json(_state_path(), {})
            completed = _normalize_state(state_raw if isinstance(state_raw, dict) else {})
            day_done = completed.get(dkey) or {}
            for win in WINDOWS:
                if not day_done.get(win.key) and slot_due(now, win.hour, win.minute):
                    run_for_window(now.date(), win, force=False)
                    time.sleep(65)
        time.sleep(20)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    ap = argparse.ArgumentParser(description="Premarket DeepSeek V4 cloud (2× daily, report-only)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--window", help="Single window key (premarket|intraday)")
    args = ap.parse_args()
    set_test_mode(bool(args.test or os.getenv("AETHER_TEST", "").lower() in ("1", "true", "yes")))
    if _test_mode:
        STATE_TEST_DIR.mkdir(parents=True, exist_ok=True)

    wins = WINDOWS
    if args.window:
        wins = [w for w in WINDOWS if w.key == args.window]
        if not wins:
            raise SystemExit(f"unknown window: {args.window}")

    trade_date = dt.date.fromisoformat(args.date) if args.date else _schedule_now().date()
    if args.loop and not args.once:
        scheduler_loop()
        return
    if len(wins) == 1:
        out = run_for_window(trade_date, wins[0], force=args.force)
    else:
        out = run_for_date(trade_date, force=args.force, windows=wins)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
