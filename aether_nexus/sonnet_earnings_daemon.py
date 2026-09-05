#!/usr/bin/env python3
"""Sonnet earnings lane — T+1/T+2 verified catalyst scan, report-only, CC CLI."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
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
if str(REPO_ROOT / "aether-paper") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "aether-paper"))

from aether_shared import EST, atomic_write_json  # noqa: E402
from aether_grid_emit import emit_sonnet_earnings  # noqa: E402
from earnings_catalyst import earnings_in_window, verify_earnings_date  # noqa: E402
from earnings_confabulation import detect_confabulation, validate_earnings_item  # noqa: E402
from earnings_integrity import earnings_engine_blocked, sanitize_anomaly_flag  # noqa: E402
from premarket_ab_isolation import assert_sonnet_no_retrieval_tools  # noqa: E402
from cc_cli_capture import CliLane, claude_capture  # noqa: E402
from daemon_schedule import parse_hhmm, slot_due  # noqa: E402

try:
    from aether_dryrun import POOL_SYMBOLS, is_trading_day
except Exception:
    POOL_SYMBOLS = os.getenv("POOL_SYMBOLS", "NVDA,TSLA,MU").split(",")
    def is_trading_day(d: dt.date | None = None) -> bool:
        d = d or dt.datetime.now(EST).date()
        return d.weekday() < 5

logger = logging.getLogger("SonnetEarnings")
STATE_PATH = BASE_DIR / "sonnet_earnings_state.json"
EARNINGS_TIME = os.getenv("SONNET_EARNINGS_TIME", "06:30")

SONNET_EARNINGS_SYSTEM = """你是 Aether Nexus 财报前期权扫描节点（sonnet-earnings lane）。report-only，不输出交易指令。
输入仅含 prompt 内财报日历与行情/期权读数；不得以训练知识补充或修正任何日期/数值。
输出 0 或 1 个 Top 1 候选，严格格式：

标的：SYMBOL|方向：多|为什么：（逐条对应过滤器读数）|风险：（一句）|置信：[高置信/试探性/观察]|info_basis：[snapshot/world-knowledge/mixed]

若无合格候选，只输出一行：SKIP|原因：（一句）
prompt 尾部约束：事实字段仅来自输入；缺失即 SKIP。"""

CONSTRAINT_TAIL = (
    "\n\n【硬约束】财报日期、IV、spread、期权量等事实仅以本 prompt 为准；"
    "不得以训练知识补充或修正；事实缺失即 SKIP。"
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _universe_symbols() -> list[str]:
    syms = sorted({s.strip().upper() for s in POOL_SYMBOLS if s.strip()})
    extra = os.getenv("EARNINGS_WATCHLIST", "")
    for s in extra.split(","):
        s = s.strip().upper()
        if s and s not in syms:
            syms.append(s)
    return syms


def build_earnings_prompt(trade_date: dt.date, candidates: list[dict[str, Any]]) -> str:
    lines = [
        f"交易日：{trade_date.isoformat()}",
        "任务：T+1 至 T+2 内有 verified 财报的标的，选 Top 1 或 SKIP。",
        "候选（双源 verified 才列入）：",
    ]
    if not candidates:
        lines.append("（无 verified 候选 — 必须 SKIP）")
    for c in candidates:
        lines.append(
            f"- {c['symbol']} 财报 {c['date']} (T+{c['days_to_earnings']}) "
            f"sources calendar={c['sources']['calendar']} info={c['sources']['info']}"
        )
    return "\n".join(lines) + CONSTRAINT_TAIL


def parse_earnings_item(text: str) -> dict[str, Any] | None:
    if not text or text.strip().upper().startswith("SKIP"):
        return None
    m = re.search(
        r"标的：([A-Z]{1,5})\|方向：([^|]+)\|为什么：([^|]+)\|风险：([^|]+)\|置信：\[([^\]]+)\]"
        r"(?:\|info_basis：\[([^\]]+)\])?",
        text,
    )
    if not m:
        return None
    sym, direction, why, risk, conf, basis = m.groups()
    return {
        "sym": sym.upper(),
        "value": f"{direction.strip()} · [{conf.strip()}]",
        "note": f"{why.strip()} | 风险：{risk.strip()}",
        "dir": 1 if "多" in direction else -1 if "空" in direction else 0,
        "confidence": conf.strip(),
        "info_basis": (basis or "snapshot").strip(),
        "raw": text.strip(),
    }


def scan_verified_universe(trade_date: dt.date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym in _universe_symbols():
        hit = earnings_in_window(sym, min_days=1, max_days=2, today=trade_date)
        if hit:
            out.append(hit)
    return out


def run_for_date(trade_date: dt.date, *, force: bool = False) -> dict[str, Any]:
    state = _read_json(STATE_PATH, {"completed_dates": []})
    dkey = trade_date.isoformat()
    if not force and dkey in (state.get("completed_dates") or []):
        return {"skipped": True, "trade_date": dkey}

    verified = scan_verified_universe(trade_date)
    user_prompt = build_earnings_prompt(trade_date, verified)
    assert_sonnet_no_retrieval_tools(system_prompt=SONNET_EARNINGS_SYSTEM)
    lane = CliLane(
        cli_model=os.getenv("SONNET_EARNINGS_CLI_MODEL", "claude-sonnet-4-6"),
        label="sonnet-earnings",
    )
    text, meta = claude_capture(f"{SONNET_EARNINGS_SYSTEM}\n\n{user_prompt}", lane)
    meta = dict(meta)
    meta["route"] = "cc_cli"
    meta["verified_candidates"] = len(verified)

    item = parse_earnings_item(text)
    confab_hits: list[str] = []
    skip_reason = ""
    if not verified:
        skip_reason = "no verified T+1/T+2 catalyst"
    if text and text.strip().upper().startswith("SKIP"):
        skip_reason = skip_reason or (text.strip().split("|", 1)[-1].strip() or "model SKIP")
    if item:
        ok, confab_hits = validate_earnings_item(prompt=user_prompt, item=item)
        if not ok:
            logger.warning("earnings drop sym=%s hits=%s", item.get("sym"), confab_hits)
            skip_reason = "constitution/confabulation: " + ",".join(confab_hits[:4])
            item = None
        else:
            extra = detect_confabulation(prompt=user_prompt, output=text)
            if extra:
                confab_hits = extra
                skip_reason = "confabulation: " + ",".join(extra[:4])
                item = None
    elif not skip_reason:
        skip_reason = "parse_empty_or_unverified"

    blocked, block_reasons = earnings_engine_blocked(meta.get("integrity_flags") or [])
    meta["engine_integrity_ok"] = not blocked
    meta["engine_integrity_reasons"] = block_reasons
    meta["verified_candidates"] = len(verified)
    if not item:
        meta["skip_reason"] = skip_reason

    result: dict[str, Any] = {
        "trade_date": dkey,
        "generated_at": dt.datetime.now(EST).isoformat(),
        "item": item,
        "verified_universe": verified,
        "raw_excerpt": (text or "")[:2000],
        "meta": meta,
        "confabulation_hits": confab_hits,
        "skip_reason": skip_reason if not item else "",
    }
    # Always emit — empty Top1 must still paint EARNINGS section (E-5), never silent absence.
    emit_sonnet_earnings(trade_date=dkey, item=item, meta=meta)
    try:
        from paper.options_ledger import record_entry, read_trades_summary
        from paper.store import init_sonnet_earnings_lane, is_lane_initialized
        from paper.emit import emit_sonnet_earnings_wallet

        if not is_lane_initialized("sonnet_earnings"):
            init_sonnet_earnings_lane(days=30, start_equity=1000.0)
        contract = meta.get("contract") if isinstance(meta.get("contract"), dict) else None
        if item and contract and contract.get("strike") and contract.get("expiry"):
            sym = item["sym"]
            hit = next((v for v in verified if v["symbol"] == sym), None)
            from paper.options_ledger import read_trades_summary
            # M: prevent --force re-runs from duplicating entries. If an open entry
            # already exists for this (symbol, strike, expiry, trade_date), skip the
            # insert instead of appending a second entry.
            _existing = read_trades_summary().get("open", [])
            _dup = any(
                r.get("symbol") == sym
                and str(r.get("strike")) == str(contract["strike"])
                and str(r.get("expiry")) == str(contract["expiry"])
                and r.get("trade_date") == dkey
                for r in _existing
            )
            if _dup:
                logger.info("sonnet-earnings skip duplicate entry for %s %s %s %s (force re-run)",
                            sym, contract["strike"], contract["expiry"], dkey)
            else:
                raw_delta = contract.get("delta")
                if raw_delta is None or raw_delta == "":
                    # M: do NOT fabricate delta=0.4 — record None + a delta_source flag
                    # so the ledger doesn't pretend a greek it never had.
                    delta_val = None
                    delta_source = "missing"
                else:
                    delta_val = float(raw_delta)
                    delta_source = "market"
                record_entry(
                    symbol=sym,
                    strike=float(contract["strike"]),
                    expiry=str(contract["expiry"]),
                    entry_premium=float(contract.get("entry_premium") or 0),
                    entry_iv=float(contract.get("entry_iv") or 0),
                    delta=delta_val,
                    trade_date=dkey,
                    earnings_date=hit["date"] if hit else dkey,
                    meta={"scan": "e2", "info_basis": item.get("info_basis"),
                          "contract_type": "call", "delta_source": delta_source},
                )
        emit_sonnet_earnings_wallet(trades_summary=read_trades_summary())
    except Exception as exc:
        logger.warning("sonnet-earnings paper wallet emit skipped: %s", exc)
    if item:
        logger.info("sonnet-earnings emitted Top 1 %s", item.get("sym"))
    else:
        logger.info("sonnet-earnings skip emit verified=%d reason=%s", len(verified), skip_reason)

    ts_now = dt.datetime.now(dt.timezone.utc).isoformat()
    state["last_success_ts"] = ts_now
    state["last_success_date"] = dkey
    completed = state.setdefault("completed_dates", [])
    if dkey not in completed:
        completed.append(dkey)
    if not item:
        state["last_no_emit_ts"] = ts_now
        state["last_skip_reason"] = skip_reason
    atomic_write_json(str(STATE_PATH), state)
    return result


def scheduler_loop() -> None:
    hour, minute = parse_hhmm(EARNINGS_TIME)
    logger.info("sonnet-earnings daemon | fire at %02d:%02d EST", hour, minute)
    while True:
        now = dt.datetime.now(EST)
        if now.weekday() < 5 and is_trading_day(now.date()):
            dkey = now.date().isoformat()
            state = _read_json(STATE_PATH, {"completed_dates": []})
            if dkey not in (state.get("completed_dates") or []) and slot_due(now, hour, minute):
                run_for_date(now.date(), force=False)
                time.sleep(65)
        time.sleep(20)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    ap = argparse.ArgumentParser(description="Sonnet earnings lane (report-only)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--verify-only", action="store_true", help="Print verified universe only")
    args = ap.parse_args()
    trade_date = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(EST).date()
    if args.verify_only:
        print(json.dumps(scan_verified_universe(trade_date), ensure_ascii=False, indent=2))
        return
    if args.loop and not args.once:
        scheduler_loop()
        return
    print(json.dumps(run_for_date(trade_date, force=args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
