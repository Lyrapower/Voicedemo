"""Risk budget — equity-scaled per spec; snapshot persisted with calc date."""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
from typing import Any

from aether_shared import EST

REPO_ROOT = Path(__file__).resolve().parents[2]
PAPER_STATE = REPO_ROOT / "aether-paper" / "state"
SNAPSHOT_PATH = Path(__file__).resolve().parent / "state" / "risk_budget.json"

ACCOUNT_LANE = os.getenv("OFFPOOL_ACCOUNT_LANE", "equity").strip() or "equity"

RISK_BUDGET_PCT = float(os.getenv("RISK_BUDGET_PCT", "0.015"))
FUSE_PREMIUM_PCT = float(os.getenv("FUSE_PREMIUM_PCT", "-0.40"))
STOP_AUTHORITY = os.getenv("STOP_AUTHORITY", "structural").strip() or "structural"
STOP_AUTHORITY_NOTE = (
    "underlying level, 5-min close confirm — premium % has no stop authority"
)

SIZING_FORMULA = (
    "floor(RISK_BUDGET_USD ÷ (entry_premium − structural_stop_premium) ÷ 100)"
)


def _heartbeat_path(lane: str) -> Path:
    return PAPER_STATE / f"heartbeat{'' if lane == 'equity' else f'_{lane}'}.json"


def _account_path(lane: str) -> Path:
    return PAPER_STATE / f"account{'' if lane == 'equity' else f'_{lane}'}.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _equity_from_account_marks(lane: str) -> float | None:
    acc = _load_json(_account_path(lane))
    if not acc:
        return None
    cash = float(acc.get("cash") or 0)
    positions = acc.get("positions") or {}
    if not positions:
        return round(cash, 2)

    paper_root = REPO_ROOT / "aether-paper"
    import sys

    if str(paper_root) not in sys.path:
        sys.path.insert(0, str(paper_root))
    try:
        from paper import equity_feed

        syms = {str(p.get("symbol") or s) for s, p in positions.items()}
        marks = equity_feed.marks(syms)
    except Exception:
        marks = {}

    pos_val = 0.0
    for sym, p in positions.items():
        px = marks.get(sym) or marks.get(str(p.get("symbol") or sym))
        if px is None:
            px = float(p.get("entry_price") or 0)
        pos_val += float(p.get("qty") or 0) * float(px)
    return round(cash + pos_val, 2)


def fetch_account_equity_usd(*, lane: str | None = None) -> tuple[float, str]:
    """Return (equity_usd, source_tag)."""
    lane = lane or ACCOUNT_LANE
    hb = _load_json(_heartbeat_path(lane))
    eq = hb.get("equity")
    if eq is not None and float(eq) > 0:
        return round(float(eq), 2), f"heartbeat:{lane}"

    computed = _equity_from_account_marks(lane)
    if computed is not None and computed > 0:
        return computed, f"account_marks:{lane}"

    raise FileNotFoundError(
        f"no account equity for lane={lane!r} — check {PAPER_STATE} heartbeat/account"
    )


def size_contracts(
    entry_premium: float,
    structural_stop_premium: float,
    *,
    risk_budget_usd: float | None = None,
) -> int:
    """Contracts sized to structural premium risk (not underlying % stop).

    M: when budget<=0 or per_contract<=0 (bad stop math / no budget), return 0 but
    surface a reason so the caller can flag the sizing failure instead of silently
    getting 0 contracts.
    """
    budget = risk_budget_usd if risk_budget_usd is not None else 0.0
    per_contract = (float(entry_premium) - float(structural_stop_premium)) * 100.0
    if budget <= 0:
        return 0, "no_budget"
    if per_contract <= 0:
        return 0, f"bad_stop_math:per_contract={per_contract:.2f}"
    return int(math.floor(budget / per_contract)), None


def resolve_risk_budget(
    *,
    trade_date: dt.date | None = None,
    force_env_usd: bool = False,
) -> dict[str, Any]:
    """Compute RISK_BUDGET_USD from account × pct; persist snapshot with as_of date.

    M5: live account equity is the default source. `RISK_BUDGET_USD` env is only
    used when `force_env_usd=True` (explicit override) — previously the default
    `True` made a stale/hardcoded env value silently shadow the real account.
    """
    trade_date = trade_date or dt.datetime.now(EST).date()
    as_of = trade_date.isoformat()

    env_usd = os.getenv("RISK_BUDGET_USD", "").strip()
    if force_env_usd and env_usd:
        usd = round(float(env_usd), 2)
        snap = {
            "as_of": as_of,
            "account_lane": ACCOUNT_LANE,
            "account_equity_usd": None,
            "equity_source": "env:RISK_BUDGET_USD",
            "risk_budget_pct": RISK_BUDGET_PCT,
            "risk_budget_usd": usd,
            "fuse_premium_pct": FUSE_PREMIUM_PCT,
            "stop_authority": STOP_AUTHORITY,
            "stop_authority_note": STOP_AUTHORITY_NOTE,
            "sizing_formula": SIZING_FORMULA,
        }
    else:
        equity, src = fetch_account_equity_usd()
        usd = round(equity * RISK_BUDGET_PCT, 2)
        snap = {
            "as_of": as_of,
            "account_lane": ACCOUNT_LANE,
            "account_equity_usd": equity,
            "equity_source": src,
            "risk_budget_pct": RISK_BUDGET_PCT,
            "risk_budget_usd": usd,
            "fuse_premium_pct": FUSE_PREMIUM_PCT,
            "stop_authority": STOP_AUTHORITY,
            "stop_authority_note": STOP_AUTHORITY_NOTE,
            "sizing_formula": SIZING_FORMULA,
        }

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snap


def risk_budget_for_payload(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "max_loss_per_trade_usd": snap.get("risk_budget_usd"),
        "risk_budget_pct": snap.get("risk_budget_pct"),
        "account_equity_usd": snap.get("account_equity_usd"),
        "as_of": snap.get("as_of"),
        "account_lane": snap.get("account_lane"),
        "equity_source": snap.get("equity_source"),
        "fuse_premium_pct": snap.get("fuse_premium_pct"),
        "stop_authority": snap.get("stop_authority"),
        "stop_authority_note": snap.get("stop_authority_note"),
        "sizing_formula": snap.get("sizing_formula"),
        "note": "RISK_BUDGET_USD = account_equity × risk_budget_pct at as_of",
    }
