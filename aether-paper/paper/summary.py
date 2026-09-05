"""Paper 摘要 —— brief / 16:40 日报 / Aster compile / crypto A/B 单一事实源。"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from . import crypto_feed
from . import equity_feed
from .store import (
    AB_FEE_SLIPPAGE_MODEL,
    AB_BG_ANCHOR_NOTE,
    CRYPTO_AB_LANES,
    CRYPTO_AB_UNIVERSE,
    CRYPTO_FEED_DEFAULT,
    LANE_REGISTRY,
    PAPER_TICK_LANES,
    ab_contract_template,
    is_lane_initialized,
    lane_paths,
    load_account,
    load_experiment,
    read_jsonl,
)


def _marks_for_lane(lane: str, symbols: set[str]) -> dict[str, float]:
    if lane.startswith("crypto"):
        return crypto_feed.marks(sorted(symbols), prefer=CRYPTO_FEED_DEFAULT)
    return equity_feed.marks(symbols)


def btc_buyhold_return_pct(experiment: dict | None) -> float | None:
    if not experiment:
        return None
    anchor = float(experiment.get("btc_anchor_price") or 0)
    if anchor <= 0:
        return None
    cur = crypto_feed.spot_price("BTC-USD", prefer=CRYPTO_FEED_DEFAULT)
    if cur is None:
        return None
    return round((cur / anchor - 1) * 100, 2)


def lane_return_pct(equity: float, start_equity: float) -> float:
    if not start_equity:
        return 0.0
    return round((equity / start_equity - 1) * 100, 2)


def background_return_pct(
    lane: str, equity: float, start_equity: float, experiment: dict | None
) -> float | None:
    """Crypto: excess vs BTC B&H. Equity: absolute return."""
    lane_ret = lane_return_pct(equity, start_equity)
    if not lane.startswith("crypto"):
        return lane_ret
    btc_ret = btc_buyhold_return_pct(experiment)
    if btc_ret is None:
        return lane_ret
    return round(lane_ret - btc_ret, 2)


def uninitialized_lane_row(lane: str) -> dict[str, Any]:
    reg = LANE_REGISTRY.get(lane, {})
    title = "RULES" if lane == "crypto_rules" else "SONNET 4.6" if lane == "crypto_cli" else lane
    return {
        "lane": lane,
        "owner": reg.get("owner", "unknown"),
        "asset_class": reg.get("asset_class", "unknown"),
        "title": title,
        "status": "uninitialized",
        "equity": None,
        "cash": None,
        "start_equity": None,
        "return_pct": None,
        "return_pct_background": None,
        "n_positions": 0,
        "positions": [],
        "position_state": "uninitialized",
        "risk_rejections": 0,
    }


def lane_snapshot(lane: str) -> dict[str, Any] | None:
    if not is_lane_initialized(lane):
        return None
    acc = load_account(lane)
    if acc is None:
        return None
    syms = set(acc.positions.keys())
    marks = _marks_for_lane(lane, syms) if syms else {}
    for s, p in acc.positions.items():
        marks.setdefault(s, p.entry_price)
    eq = acc.equity(marks)
    exp = load_experiment(lane)
    paths = lane_paths(lane)
    decisions = read_jsonl(paths["decisions"])
    enters = [d for d in decisions if d.get("action") == "enter"]
    exits = [d for d in decisions if d.get("action") == "exit"]
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    today_dec = [d for d in decisions if str(d.get("ts", "")).startswith(today)]
    lane_ret = lane_return_pct(eq, acc.start_equity)
    bg = background_return_pct(lane, eq, acc.start_equity, exp)
    pos_keys = list(acc.positions.keys())
    since_iso = (exp or {}).get("started_at")
    since_mmdd = None
    if since_iso:
        try:
            since_mmdd = str(since_iso)[5:10].replace("-", "-")  # MM-DD
            if len(since_mmdd) == 5:
                pass
        except Exception:
            since_mmdd = None
    return {
        "lane": lane,
        "owner": LANE_REGISTRY.get(lane, {}).get("owner", "unknown"),
        "asset_class": LANE_REGISTRY.get(lane, {}).get("asset_class", "unknown"),
        "aggregation_scope": LANE_REGISTRY.get(lane, {}).get("owner", "?")
        + ":" + LANE_REGISTRY.get(lane, {}).get("asset_class", "?"),
        "status": "ready",
        "cash": acc.cash,
        "equity": eq,
        "start_equity": acc.start_equity,
        "return_pct": lane_ret,
        "return_pct_background": bg,
        "since_iso": since_iso,
        "since_mmdd": since_mmdd,
        "exposure_pct": acc.exposure_pct(marks),
        "n_positions": len(acc.positions),
        "positions": pos_keys,
        "position_state": "flat" if not acc.positions else "held",
        "experiment": exp,
        "n_enters": len(enters),
        "n_exits": len(exits),
        "n_today": len(today_dec),
        "risk_rejections": sum(1 for d in enters if not d.get("allowed")),
    }


def lane_row(lane: str) -> dict[str, Any]:
    """Always returns a row — uninitialized lanes never omitted."""
    snap = lane_snapshot(lane)
    if snap:
        return snap
    return uninitialized_lane_row(lane)


def _lane_tag(lane: str) -> str:
    return {
        "equity": "paper·eq",
        "crypto_rules": "paper·₿rules",
        "crypto_cli": "paper·₿cli",
    }.get(lane, f"paper·{lane}")


def _format_lane_value(row: dict[str, Any]) -> str:
    if row.get("status") == "uninitialized":
        return "未初始化"
    eq = row.get("equity")
    if eq is None:
        return "未初始化"
    if row.get("n_positions", 0) == 0 and eq == row.get("start_equity"):
        return f"${eq:.0f} · 空仓"
    return f"${eq:.0f}"


def _format_lane_note(row: dict[str, Any]) -> str:
    if row.get("status") == "uninitialized":
        return "账本未初始化 · broker=false"
    bg = row.get("return_pct_background")
    bg_s = f"{bg:+.2f}%" if bg is not None else "—"
    pos = ",".join(row.get("positions") or []) or "flat"
    return (
        f"{row.get('n_positions', 0)} pos [{pos}] · "
        f"bg {bg_s} vs BTC · broker=false"
    )


def paper_brief_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for lane in PAPER_TICK_LANES:
        row = lane_row(lane)
        items.append(
            {
                "sym": _lane_tag(lane),
                "label": "mock_wallet",
                "value": _format_lane_value(row),
                "note": _format_lane_note(row),
                "dir": 0 if row.get("status") == "uninitialized" else (1 if (row.get("return_pct_background") or 0) >= 0 else -1),
                "src": "paper",
                "lane": lane,
                "status": row.get("status", "ready"),
            }
        )
    return items


def paper_journal_block() -> str:
    lines = ["Paper mock (broker_execution=false):"]
    for lane in PAPER_TICK_LANES:
        row = lane_row(lane)
        if row.get("status") == "uninitialized":
            lines.append(f"  {lane}: 未初始化")
            continue
        pos = ",".join(row["positions"]) or "flat"
        bg = row.get("return_pct_background")
        bg_s = f"{bg:+.2f}%" if bg is not None else "—"
        lines.append(
            f"  {lane}: equity=${row['equity']:.2f} cash=${row['cash']:.2f} "
            f"pos={row['n_positions']} [{pos}] bg={bg_s} vs BTC"
        )
    return "\n".join(lines)


def _ab_divergence_warnings() -> list[str]:
    rules_exp = load_experiment("crypto_rules") or {}
    cli_exp = load_experiment("crypto_cli") or {}
    rules_c = rules_exp.get("ab_contract") or ab_contract_template("crypto_rules")
    cli_c = cli_exp.get("ab_contract") or ab_contract_template("crypto_cli")
    diffs: list[str] = []
    for key in ("feed", "fee_slippage_model", "tradable_universe"):
        if rules_c.get(key) != cli_c.get(key):
            diffs.append(f"{key}: rules≠cli")
    r_feed = rules_exp.get("btc_anchor_price")
    c_feed = cli_exp.get("btc_anchor_price")
    if r_feed and c_feed and abs(float(r_feed) - float(c_feed)) > 0.01:
        diffs.append("btc_anchor_price: init-time BTC mark differs between lanes")
    return diffs


def crypto_ab_payload() -> dict[str, Any]:
    """Side-by-side crypto A/B — cli 未初始化也占行, 禁止隐身。"""
    cols: list[dict[str, Any]] = []
    for lane in CRYPTO_AB_LANES:
        row = lane_row(lane)
        cols.append(
            {
                "lane": lane,
                "title": "RULES" if lane == "crypto_rules" else "SONNET 4.6",
                "status": row.get("status", "ready"),
                "equity": row.get("equity"),
                "cash": row.get("cash"),
                "start_equity": row.get("start_equity"),
                "return_pct": row.get("return_pct"),
                "return_pct_background": row.get("return_pct_background"),
                "n_positions": row.get("n_positions", 0),
                "positions": row.get("positions") or [],
                "position_state": row.get("position_state"),
                "risk_rejections": row.get("risk_rejections", 0),
            }
        )
    return {
        "label": "CRYPTO PAPER A/B",
        "broker_execution": False,
        "isolated_from": ["offpool", "equity_scan", "ib_daemon"],
        "isolated_ledgers": True,
        "ab_contract": {
            "bg_anchor": AB_BG_ANCHOR_NOTE,
            "bg_formula": "return_pct_background = lane_return_pct - btc_buyhold_return_pct",
            "feed": f"{CRYPTO_FEED_DEFAULT} primary, kraken fallback",
            "fee_slippage_model": AB_FEE_SLIPPAGE_MODEL,
            "tradable_universe": list(CRYPTO_AB_UNIVERSE),
            "three_same": "same feed · same fee/slippage model · same tradable universe",
            "isolated_ledgers_invariant": "A/B lanes never merge accounts, fills, or PnL",
        },
        "ab_divergence": _ab_divergence_warnings(),
        "columns": cols,
    }


def daily_report_payload(trade_date: str | None = None) -> dict[str, Any]:
    trade_date = trade_date or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    lanes = [lane_row(lane) for lane in PAPER_TICK_LANES]
    body_lines = [
        f"Paper daily · {trade_date} · broker_execution=false",
        "",
    ]
    for row in lanes:
        if row.get("status") == "uninitialized":
            body_lines.append(f"{row['lane']}: 未初始化")
            continue
        bg = row.get("return_pct_background")
        bg_s = f"{bg:+.2f}%" if bg is not None else "—"
        body_lines.append(
            f"{row['lane']} ({row.get('owner','?')}/{row.get('asset_class','?')}): "
            f"${row['equity']:.2f} ({bg_s} bg) pos={row['n_positions']} today={row['n_today']}"
        )
    ab = crypto_ab_payload()
    rules = next((c for c in ab["columns"] if c["lane"] == "crypto_rules"), {})
    cli = next((c for c in ab["columns"] if c["lane"] == "crypto_cli"), {})
    body_lines.append("")
    r_val = "未初始化" if rules.get("status") == "uninitialized" else f"${rules.get('equity')}"
    c_val = "未初始化" if cli.get("status") == "uninitialized" else f"${cli.get('equity')}"
    body_lines.append(
        f"Crypto A/B: rules {r_val} vs cli {c_val} (isolated ledgers, no merge)"
    )
    return {
        "date": trade_date,
        "title": f"Paper 日报 · {trade_date}",
        "body": "\n".join(body_lines),
        "lanes": lanes,
        "crypto_ab": ab,
        "broker_execution": False,
        "aggregation_note": "equity=grid only; crypto A/B isolated; sonnet_earnings separate",
        "items": paper_brief_items(),
    }


def paper_state_root() -> Path:
    return Path(__file__).resolve().parent.parent / "state"
