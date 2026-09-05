#!/usr/bin/env python3
"""Aether paper daemon — equity + crypto A/B lanes (rules vs CC CLI sonnet)."""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from paper.account import PaperAccount  # noqa: E402
from paper import engine as E  # noqa: E402
from paper import equity_feed  # noqa: E402
from paper import crypto_feed  # noqa: E402
from paper.emit import (  # noqa: E402
    emit_paper_fill,
    emit_paper_wallet,
    emit_paper_wallet_uninitialized,
    emit_sonnet_earnings_wallet,
)
from paper.options_ledger import read_trades_summary  # noqa: E402
from paper.store import (  # noqa: E402
    PAPER_TICK_LANES,
    append_jsonl,
    init_experiment,
    is_lane_initialized,
    lane_paths,
    load_account,
    load_experiment,
    load_processed,
    read_jsonl,
    save_account,
    save_processed,
    atomic_write_json,
)
from paper.summary import background_return_pct  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("paper_daemon")

from zoneinfo import ZoneInfo  # noqa: E402
EST = ZoneInfo("America/New_York")  # DST-aware, replaces fixed UTC-5
TICK_SEC = int(os.getenv("PAPER_TICK_SEC", "120"))
TRADING_START = os.getenv("TRADING_START", "10:00")
TRADING_END = os.getenv("TRADING_END", "15:00")
CRYPTO_ENABLED = os.getenv("PAPER_CRYPTO_ENABLED", "true").lower() in ("1", "true", "yes")


def _parse_hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def equity_entry_window(now: dt.datetime | None = None) -> bool:
    if os.getenv("PAPER_FORCE_ENTRY", "").lower() in ("1", "true", "yes"):
        return True
    now = now or dt.datetime.now(EST)
    if now.weekday() >= 5:
        return False
    sh, sm = _parse_hm(TRADING_START)
    eh, em = _parse_hm(TRADING_END)
    cur = now.hour * 60 + now.minute
    return sh * 60 + sm <= cur <= eh * 60 + em


def fetch_marks(lane: str, symbols: set[str]) -> dict[str, float]:
    if lane.startswith("crypto"):
        return crypto_feed.marks(sorted(symbols), prefer=os.getenv("CRYPTO_FEED", "coinbase"))
    return equity_feed.marks(symbols)


def position_rows(acc: PaperAccount, marks: dict[str, float]) -> list[dict]:
    rows = []
    for sym, pos in acc.positions.items():
        px = marks.get(sym, pos.entry_price)
        upnl = round((px - pos.entry_price) * pos.qty, 2)
        rows.append(
            {
                "sym": sym,
                "qty": pos.qty,
                "entry": pos.entry_price,
                "mark": px,
                "stop": pos.stop_price,
                "upnl": upnl,
                "reason": pos.reason[:80],
            }
        )
    return rows


def process_inbox(
    acc: PaperAccount,
    marks: dict[str, float],
    processed: set[str],
    *,
    lane: str,
    allow_entry: bool,
) -> list[dict]:
    if not allow_entry:
        return []
    paths = lane_paths(lane)
    decisions: list[dict] = []
    for sig in read_jsonl(paths["inbox"]):
        key = sig.get("key") or f"{sig.get('scan_time')}|{sig.get('symbol')}"
        if key in processed:
            continue
        sym = str(sig.get("symbol") or "").upper()
        if not sym:
            continue
        px = marks.get(sym)
        price_source = "live_mark"
        price_stale = False
        if px is None:
            ref = float(sig.get("ref_price") or 0)
            if ref > 0:
                # M6: live mark missing — fall back to scan ref_price, but stamp as
                # stale so the entry is visibly priced off an old scan, not a live feed.
                px = ref
                price_source = "scan_ref_price"
                price_stale = True
            else:
                continue
        rec = E.enter(
            acc,
            sym,
            px,
            float(sig.get("want_pct") or 0),
            str(sig.get("reason") or "scan"),
            marks,
        )
        rec["price_source"] = price_source
        rec["price_stale"] = price_stale
        append_jsonl(paths["decisions"], rec)
        emit_paper_fill(rec, lane=lane)
        decisions.append(rec)
        processed.add(key)
    save_processed(processed, lane=lane)
    return decisions


def tick_lane(lane: str) -> dict:
    paths = lane_paths(lane)
    if lane == "sonnet_earnings":
        summary = read_trades_summary()
        payload = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "lane": lane,
            "status": "ready" if is_lane_initialized(lane) else "uninitialized",
            "n_positions": len(summary["open"]),
            "n_closed": len(summary["closed"]),
            "discipline_breach_count": summary["discipline_breach_count"],
            "broker_execution": False,
        }
        atomic_write_json(paths["heartbeat"], payload)
        emit_sonnet_earnings_wallet(trades_summary=summary, force=False)
        return payload

    # crypto_cli: 未显式初始化 → 只 emit uninitialized, 禁止偷建 $1000 账本
    if lane == "crypto_cli" and not is_lane_initialized(lane):
        emit_paper_wallet_uninitialized(lane=lane, force=False)
        return {"lane": lane, "status": "uninitialized", "broker_execution": False}

    acc = load_account(lane)
    if acc is None:
        # M14: previously every non-crypto_cli lane auto-created a $1000 PaperAccount
        # on the first tick — an unintended paper experiment start. Now require an
        # explicit opt-in via PAPER_AUTO_INIT=1; otherwise emit uninitialized and
        # wait for the explicit init path (e.g. init_sonnet_earnings_lane).
        if os.getenv("PAPER_AUTO_INIT", "").strip() not in ("1", "true", "True"):
            emit_paper_wallet_uninitialized(lane=lane, force=False)
            logger.info("lane %s uninitialized — set PAPER_AUTO_INIT=1 to auto-create account", lane)
            return {"lane": lane, "status": "uninitialized", "broker_execution": False}
        acc = PaperAccount()
        if not load_experiment(lane):
            init_experiment(days=int(os.getenv("PAPER_EXPERIMENT_DAYS", "30")), lane=lane)
        save_account(acc, lane=lane)
        logger.info("Initialized %s paper account $%.2f", lane, acc.start_equity)

    symbols = set(acc.positions.keys())
    for sig in read_jsonl(paths["inbox"])[-30:]:
        sym = str(sig.get("symbol") or "").upper()
        if sym:
            symbols.add(sym)

    marks = fetch_marks(lane, symbols)
    for sym, pos in acc.positions.items():
        marks.setdefault(sym, pos.entry_price)

    decisions: list[dict] = []
    for rec in E.check_stops(acc, marks):
        append_jsonl(paths["decisions"], rec)
        emit_paper_fill(rec, lane=lane)
        decisions.append(rec)

    if lane == "equity":
        allow_entry = equity_entry_window()
    else:
        allow_entry = True  # crypto lanes 24/7

    processed = load_processed(lane=lane)
    decisions.extend(process_inbox(acc, marks, processed, lane=lane, allow_entry=allow_entry))

    save_account(acc, lane=lane)
    exp = load_experiment(lane=lane) or {}
    if lane.startswith("crypto") and not exp.get("btc_anchor_price"):
        btc = crypto_feed.spot_price("BTC-USD", prefer=os.getenv("CRYPTO_FEED", "coinbase"))
        if btc:
            exp["btc_anchor_price"] = btc
            atomic_write_json(paths["experiment"], exp)
    eq = acc.equity(marks)
    bg = background_return_pct(lane, eq, acc.start_equity, exp)
    payload = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "lane": lane,
        "status": "ready",
        "equity": eq,
        "cash": acc.cash,
        "n_positions": len(acc.positions),
        "n_decisions_tick": len(decisions),
        "broker_execution": False,
        "in_entry_window": allow_entry,
        "return_pct_background": bg,
    }
    atomic_write_json(paths["heartbeat"], payload)
    emit_paper_wallet(
        cash=acc.cash,
        equity=eq,
        start_equity=acc.start_equity,
        exposure_pct=acc.exposure_pct(marks),
        positions=position_rows(acc, marks),
        experiment=exp,
        marks=marks,
        lane=lane,
        return_pct_background=bg,
        force=bool(decisions),
    )
    logger.info(
        "%s tick equity=$%.2f cash=$%.2f positions=%d decisions=%d",
        lane,
        eq,
        acc.cash,
        len(acc.positions),
        len(decisions),
    )
    return payload


def tick() -> dict:
    assert E.BROKER_EXECUTION is False
    out: dict = {}
    for lane in PAPER_TICK_LANES:
        if lane.startswith("crypto") and not CRYPTO_ENABLED:
            continue
        out[lane] = tick_lane(lane)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Aether paper loop daemon")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    if args.once or not args.loop:
        tick()
        return

    logger.info(
        "paper daemon tick=%ds lanes=%s crypto=%s broker=false",
        TICK_SEC,
        ",".join(PAPER_TICK_LANES),
        CRYPTO_ENABLED,
    )
    while True:
        try:
            tick()
        except Exception:
            logger.exception("tick failed")
        time.sleep(TICK_SEC)


if __name__ == "__main__":
    main()
