"""IV unit verification — shared with scan layer (aether_dryrun)."""
from __future__ import annotations

from typing import Any

from offpool_coach import config as cfg

# Alpaca impliedVolatility is decimal annualized vol: 0.33 = 33%, 1.121 = 112.1%.
# aether_dryrun._parse_alpaca_chain reads snap.impliedVolatility verbatim; MAX_IV=0.80.
IV_UNIT = "decimal_fraction"
IV_PATH = "alpaca_snapshot.impliedVolatility → aether_dryrun._parse_alpaca_chain → rejection_log.iv"


def iv_decimal_to_pct(iv: float) -> float:
    return round(iv * 100.0, 2)


def build_iv_context(row: dict[str, Any]) -> dict[str, Any]:
    iv = float(row.get("iv") or 0)
    kill = str(row.get("kill_rule") or "")
    threshold = float(row.get("threshold_at_kill") or cfg.MAX_IV)
    scan_veto = iv > cfg.MAX_IV or kill == "iv"
    return {
        "iv": round(iv, 4),
        "iv_pct": iv_decimal_to_pct(iv),
        "iv_unit": IV_UNIT,
        "iv_source": str(row.get("iv_source") or ""),
        "scan_max_iv": cfg.MAX_IV,
        "scan_max_iv_pct": iv_decimal_to_pct(cfg.MAX_IV),
        "iv_scan_veto": scan_veto,
        "scan_kill_rule": kill if kill else None,
        "threshold_at_kill": threshold if kill else None,
        "path_verified": IV_PATH,
        "note": (
            "112% class IV is event/extreme pricing if unit correct — not a display bug. "
            "iv_environment may single-dimension veto regardless of other scores."
            if scan_veto
            else "IV within scan cap; still judge premium vs thesis."
        ),
    }
