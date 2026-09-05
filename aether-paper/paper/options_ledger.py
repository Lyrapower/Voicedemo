"""Minimal options paper ledger for sonnet-earnings lane (E2)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .store import append_jsonl, lane_paths, read_jsonl


def _entry_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """Identity key for an option position: (symbol, strike, expiry).

    Matching on symbol alone mismatches multi-leg / same-symbol different-strike
    positions. strike/expiry are the contract identifier.
    """
    sym = str(row.get("symbol") or "").upper()
    strike = str(row.get("strike") or "")
    expiry = str(row.get("expiry") or "")
    return (sym, strike, expiry)


def _open_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair each exit with the latest still-open entry for that contract.

    A contract = (symbol, strike, expiry). Exits only close the matching contract,
    so a same-symbol different-strike entry stays open.
    """
    open_rows: list[dict[str, Any]] = []
    for row in rows:
        action = row.get("action")
        if action == "entry":
            open_rows.append(row)
        elif action == "exit":
            exit_key = _entry_key(row)
            # Only match if the exit carries strike/expiry; otherwise fall back to
            # symbol-only match for backward compat with legacy exit rows.
            has_contract = bool(exit_key[1]) and bool(exit_key[2])
            for index in range(len(open_rows) - 1, -1, -1):
                if has_contract:
                    if _entry_key(open_rows[index]) == exit_key:
                        open_rows.pop(index)
                        break
                elif str(open_rows[index].get("symbol") or "").upper() == exit_key[0]:
                    open_rows.pop(index)
                    break
    return open_rows


def record_entry(
    *,
    symbol: str,
    strike: float,
    expiry: str,
    entry_premium: float,
    entry_iv: float,
    delta: float,
    trade_date: str,
    earnings_date: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "action": "entry",
        "symbol": symbol.upper(),
        "strike": strike,
        "expiry": expiry,
        "entry_premium": entry_premium,
        "entry_iv": entry_iv,
        "IV_entry": entry_iv,
        "delta": delta,
        "trade_date": trade_date,
        "earnings_date": earnings_date,
        "meta": meta or {},
    }
    append_jsonl(lane_paths("sonnet_earnings")["trades"], row)
    return row


def read_trades_summary() -> dict[str, Any]:
    rows = read_jsonl(lane_paths("sonnet_earnings")["trades"])
    open_rows = _open_entries(rows)
    closed = [r for r in rows if r.get("action") == "exit"]
    breaches = sum(1 for r in closed if r.get("discipline_breach"))
    return {"open": open_rows, "closed": closed, "discipline_breach_count": breaches}


def record_exit(
    *,
    symbol: str,
    exit_premium: float,
    exit_iv: float,
    iv_t1_open: float | None = None,
    discipline_breach: bool = False,
    strike: float | None = None,
    expiry: str | None = None,
) -> dict[str, Any]:
    """Record an exit paired to the matching open entry by (symbol, strike, expiry).

    strike/expiry identify the contract so multi-leg or same-symbol different-strike
    positions don't cross-pair. When omitted, falls back to symbol-only match for
    legacy callers (with a warning logged via the open_ref mismatch check).
    """
    rows = read_jsonl(lane_paths("sonnet_earnings")["trades"])
    open_candidates = _open_entries(rows)
    sym_u = symbol.upper()
    open_row = None
    if strike is not None and expiry:
        target = (sym_u, str(strike), str(expiry))
        open_row = next(
            (r for r in reversed(open_candidates) if _entry_key(r) == target),
            None,
        )
    if open_row is None:
        # Fallback: symbol-only (legacy). Risk of mismatch on multi-leg — log it.
        open_row = next(
            (r for r in reversed(open_candidates) if r.get("symbol") == sym_u),
            None,
        )
    if open_row is None:
        # M: refuse to append an orphan exit (no matching open position). Previously
        # this silently appended an exit with open_ref=None / pnl_pct=None, polluting
        # the ledger and inflating the closed count with unmatched rows.
        raise ValueError(
            f"record_exit: no open entry to close for {sym_u} strike={strike} expiry={expiry}"
        )
    pnl_pct = None
    if open_row and open_row.get("entry_premium"):
        pnl_pct = round((exit_premium / float(open_row["entry_premium"]) - 1) * 100, 2)
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "action": "exit",
        "symbol": sym_u,
        "strike": strike,
        "expiry": expiry,
        "exit_premium": exit_premium,
        "IV_exit": exit_iv,
        "IV_T+1_open": iv_t1_open,
        "pnl_premium_pct": pnl_pct,
        "discipline_breach": discipline_breach,
        "open_ref": open_row,
    }
    append_jsonl(lane_paths("sonnet_earnings")["trades"], row)
    return row
