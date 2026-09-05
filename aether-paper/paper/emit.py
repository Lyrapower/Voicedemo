"""Emit paper wallet / fill / daily / crypto A/B events to Grid gateway."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

GRID_EVENTS = os.getenv("GRID_EVENTS", "http://127.0.0.1:8501/store/events")
PAPER_WALLET_EMIT_SEC = int(os.getenv("PAPER_WALLET_EMIT_SEC", "900"))

_LANE_LABELS = {
    "equity": "PAPER · equity mock",
    "crypto_rules": "PAPER · crypto RULES",
    "crypto_cli": "PAPER · crypto CLI",
    "crypto": "PAPER · crypto mock",
    "sonnet_earnings": "PAPER · sonnet_earnings",
}


def _option_contract_label(row: dict[str, Any]) -> str:
    sym = str(row.get("symbol") or "").upper()
    expiry = str(row.get("expiry") or "")
    strike = row.get("strike")
    yymmdd = expiry.replace("-", "")[2:] if len(expiry) >= 10 else expiry
    strike_s = str(int(strike)) if strike and float(strike) == int(float(strike)) else str(strike)
    return f"{sym} {yymmdd}C{strike_s}"


def _stable_wallet_sig(payload: dict[str, Any]) -> str:
    """Structure-only identity — mark-to-market equity/cash changes do not re-emit."""
    core: dict[str, Any] = {
        "lane": payload.get("lane"),
        "status": payload.get("status"),
        "position_state": payload.get("position_state"),
    }
    positions: list[dict[str, Any]] = []
    for row in payload.get("positions") or []:
        positions.append(
            {
                k: row.get(k)
                for k in (
                    "sym",
                    "contract",
                    "underlying",
                    "qty",
                    "entry",
                    "entry_premium",
                    "strike",
                    "expiry",
                    "asset_type",
                )
                if row.get(k) is not None
            }
        )
    core["positions"] = positions
    core["n_closed"] = len(payload.get("closed_trades") or [])
    if payload.get("discipline_breach_count") is not None:
        core["discipline_breach_count"] = int(payload["discipline_breach_count"])
    return json.dumps(core, sort_keys=True, ensure_ascii=False)


_LAST_WALLET: dict[str, tuple[float, str]] = {}


def _should_emit_wallet(payload: dict[str, Any], *, force: bool = False) -> bool:
    lane = str(payload.get("lane") or "equity")
    now = time.time()
    sig = _stable_wallet_sig(payload)
    last_ts, last_sig = _LAST_WALLET.get(lane, (0.0, ""))
    if force or sig != last_sig or (now - last_ts) >= PAPER_WALLET_EMIT_SEC:
        _LAST_WALLET[lane] = (now, sig)
        return True
    logger.debug(
        "skip paper_wallet lane=%s unchanged (%.0fs since last emit)",
        lane,
        now - last_ts,
    )
    return False


def _emit_paper_wallet_payload(payload: dict[str, Any], *, force: bool = False) -> bool:
    if not _should_emit_wallet(payload, force=force):
        return True
    return emit_aether("aether_paper_wallet", payload)


def reset_wallet_emit_cache() -> None:
    """Test helper — clear in-process dedupe state."""
    _LAST_WALLET.clear()


def emit_sonnet_earnings_wallet(
    *,
    trades_summary: dict[str, Any] | None = None,
    force: bool = False,
) -> bool:
    from .store import init_sonnet_earnings_lane, is_lane_initialized, lane_paths, load_account, load_experiment

    lane = "sonnet_earnings"
    if not is_lane_initialized(lane):
        init_sonnet_earnings_lane()
    acc = load_account(lane=lane)
    if acc is None:
        return emit_paper_wallet_uninitialized(lane=lane, force=force)
    exp = load_experiment(lane=lane) or {}
    summary = trades_summary or {"open": [], "closed": [], "discipline_breach_count": 0}
    positions: list[dict[str, Any]] = []
    for row in summary.get("open") or []:
        prem = float(row.get("entry_premium") or 0)
        iv_e = float(row.get("entry_iv") or row.get("IV_entry") or 0)
        contract = _option_contract_label(row)
        positions.append(
            {
                "sym": contract,
                "contract": contract,
                "underlying": row.get("symbol"),
                "strike": row.get("strike"),
                "expiry": row.get("expiry"),
                "qty": 1,
                "entry": prem,
                "entry_premium": prem,
                "entry_iv": iv_e,
                "IV_e": iv_e,
                "mark": prem,
                "asset_type": "option_call",
            }
        )
    exposure = sum(float(p.get("entry_premium") or 0) for p in positions)
    equity = float(acc.cash) + exposure
    payload: dict[str, Any] = {
        "label": _LANE_LABELS[lane],
        "lane": lane,
        "status": "ready",
        "cash": round(float(acc.cash), 2),
        "equity": round(equity, 2),
        "start_equity": float(acc.start_equity),
        "return_pct_background": round((equity / acc.start_equity - 1) * 100, 2) if acc.start_equity else 0,
        "exposure_pct": round(exposure / equity, 4) if equity else 0,
        "positions": positions,
        "closed_trades": summary.get("closed") or [],
        "discipline_breach_count": int(summary.get("discipline_breach_count") or 0),
        "broker_execution": False,
        "mode": "paper",
        "position_state": "flat" if not positions else "held",
        "asset_class": "equity_options",
        "experiment": {
            "started_at": exp.get("started_at"),
            "ends_at": exp.get("ends_at"),
            "label": exp.get("label"),
            "lane": lane,
        },
    }
    return _emit_paper_wallet_payload(payload, force=force)


def emit_aether(kind: str, payload: dict[str, Any]) -> bool:
    body = json.dumps(
        {"source": "aether", "kind": kind, "payload": payload},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        GRID_EVENTS,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("paper emit %s failed: %s", kind, exc)
        return False


def emit_paper_wallet_uninitialized(*, lane: str, force: bool = False) -> bool:
    """cli 未初始化 — 禁止 emit 假 $1000。"""
    payload: dict[str, Any] = {
        "label": _LANE_LABELS.get(lane, f"PAPER · {lane}"),
        "lane": lane,
        "status": "uninitialized",
        "equity": None,
        "cash": None,
        "start_equity": None,
        "return_pct_background": None,
        "broker_execution": False,
        "mode": "paper",
    }
    return _emit_paper_wallet_payload(payload, force=force)


def emit_paper_wallet(
    *,
    cash: float,
    equity: float,
    start_equity: float,
    exposure_pct: float,
    positions: list[dict],
    experiment: dict | None = None,
    marks: dict[str, float] | None = None,
    lane: str = "equity",
    return_pct_background: float | None = None,
    force: bool = False,
) -> bool:
    if return_pct_background is None:
        return_pct_background = round((equity / start_equity - 1) * 100, 2) if start_equity else 0.0
    payload: dict[str, Any] = {
        "label": _LANE_LABELS.get(lane, f"PAPER · {lane}"),
        "lane": lane,
        "status": "ready",
        "cash": round(cash, 2),
        "equity": round(equity, 2),
        "start_equity": start_equity,
        "return_pct_background": return_pct_background,
        "exposure_pct": exposure_pct,
        "positions": positions,
        "broker_execution": False,
        "mode": "paper",
        "position_state": "flat" if not positions else "held",
    }
    if experiment:
        payload["experiment"] = {
            "started_at": experiment.get("started_at"),
            "ends_at": experiment.get("ends_at"),
            "label": experiment.get("label"),
            "lane": experiment.get("lane", lane),
        }
    if marks:
        payload["marks"] = {k: marks[k] for k in sorted(marks)[:12]}
    return _emit_paper_wallet_payload(payload, force=force)


def emit_paper_fill(rec: dict, *, lane: str = "equity") -> bool:
    payload = {
        "lane": lane,
        "action": rec.get("action"),
        "symbol": rec.get("symbol"),
        "price": rec.get("price"),
        "want_pct": rec.get("want_pct"),
        "allowed": rec.get("allowed"),
        "risk_note": rec.get("risk_note"),
        "reason": rec.get("reason"),
        "qty": rec.get("qty"),
        "pnl": rec.get("pnl"),
        "pnl_pct": rec.get("pnl_pct"),
        "broker_execution": False,
    }
    return emit_aether("aether_paper_fill", payload)


def emit_paper_daily(payload: dict[str, Any]) -> bool:
    return emit_aether("aether_paper_daily", payload)


def emit_crypto_paper_ab(payload: dict[str, Any]) -> bool:
    return emit_aether("aether_crypto_paper_ab", payload)
