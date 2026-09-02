"""Stage 2 — assemble verified JSON payload for Fable (numbers from scan layer only)."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Literal

from aether_shared import EST

from offpool_coach import config as cfg
from offpool_coach.iv_audit import build_iv_context
from offpool_coach.schema import SCHEMA_VERSION, Payload, Window
from offpool_coach.stage1_mechanical import apply_stage1

BASE_DIR = Path(__file__).resolve().parent.parent
REJECTION_DIR = BASE_DIR / "logs" / "rejections"

_REJ_NAME = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<hms>\d{6})-(?P<id>[a-f0-9]+)\.jsonl$", re.I)


def _parse_scan_time_from_path(path: Path) -> dt.datetime:
    m = _REJ_NAME.match(path.name)
    if not m:
        return dt.datetime.now(EST)
    d = dt.date.fromisoformat(m.group("date"))
    hms = m.group("hms")
    hh, mm, ss = int(hms[:2]), int(hms[2:4]), int(hms[4:6])
    naive = dt.datetime(d.year, d.month, d.day, hh, mm, ss)
    return EST.localize(naive)


def latest_rejection_log(*, trade_date: str | None = None) -> Path | None:
    if not REJECTION_DIR.is_dir():
        return None
    files = sorted(REJECTION_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if trade_date:
        files = [p for p in files if p.name.startswith(trade_date + "_")]
    return files[0] if files else None


def _load_rejection_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows


def _best_contracts_by_symbol(rows: list[dict[str, Any]], pool_syms: set[str]) -> dict[str, dict[str, Any]]:
    """One best-score row per (symbol, strike, expiry); off-pool only."""
    best: dict[tuple[str, float, str], dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym or sym in pool_syms:
            continue
        strike = float(row.get("strike") or 0)
        expiry = str(row.get("expiry") or "")
        if not strike or not expiry:
            continue
        key = (sym, strike, expiry)
        score = float(row.get("score") or 0)
        prev = best.get(key)
        if prev is None or score > float(prev.get("score") or 0):
            best[key] = row

    by_sym: dict[str, list[dict[str, Any]]] = {}
    for (_sym, _k, _e), row in best.items():
        sym = str(row.get("symbol") or "").upper()
        by_sym.setdefault(sym, []).append(row)

    out: dict[str, dict[str, Any]] = {}
    for sym, legs in by_sym.items():
        legs.sort(key=lambda r: (-float(r.get("score") or 0), float(r.get("spread_pct") or 1)))
        out[sym] = {
            "best": legs[0],
            "chain_summary_rows": legs[:3],
        }
    return out


def _chain_leg(row: dict[str, Any], *, scan_time: dt.datetime) -> dict[str, Any]:
    bid = float(row.get("bid") or 0)
    ask = float(row.get("ask") or 0)
    mid = round((bid + ask) / 2.0, 4) if bid > 0 and ask > 0 else 0.0
    oi_src = str(row.get("oi_source") or "")
    oi_val = row.get("open_interest")
    oi_available = oi_src not in ("missing_in_snapshot", "missing") and oi_val is not None
    kill = str(row.get("kill_rule") or "").strip()
    return {
        "strike": float(row.get("strike") or 0),
        "type": "C",
        "exp": str(row.get("expiry") or ""),
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "delta": round(float(row.get("delta") or 0), 4),
        "iv": round(float(row.get("iv") or 0), 4),
        "spread_pct": round(float(row.get("spread_pct") or 0), 6),
        "volume": int(row.get("volume") or 0),
        "open_interest": int(oi_val) if oi_available else None,
        "oi_available": oi_available,
        "quote_stale": bool(row.get("quote_stale")),
        "kill_rules": [kill] if kill else [],
        "asof": scan_time.isoformat(),
    }


def _liquidity_context(row: dict[str, Any], liq_meta: dict[str, Any]) -> dict[str, Any]:
    oi_unverified = bool(liq_meta.get("oi_unverified"))
    oi_src = str(liq_meta.get("oi_source") or row.get("oi_source") or "")
    spread = float(liq_meta.get("spread_pct") or row.get("spread_pct") or 0)
    cap = cfg.LIQUIDITY_SCORE_CAP_OI_UNVERIFIED if oi_unverified else 10
    return {
        "spread_pct": round(spread, 6),
        "oi_available": not oi_unverified,
        "oi_unverified": oi_unverified,
        "open_interest": int(row.get("open_interest") or 0) if not oi_unverified else None,
        "oi_source": oi_src,
        "gate_mode": str(liq_meta.get("gate_mode") or ""),
        "score_cap": cap,
        "note": (
            f"OI unavailable — liquidity scored on spread_pct only; Fable scores.liquidity must be ≤{cap}."
            if oi_unverified
            else f"OI verified; MIN_OI={cfg.MIN_OI} applied at scan when present."
        ),
    }


def _structure_context(*, window: Window, levels: dict[str, Any] | None, atr14: float | None) -> dict[str, Any]:
    """PREMARKET v0 has no levels module — structure scoring is blind until EXECUTION wired."""
    levels_wired = (
        window == "EXECUTION"
        and levels is not None
        and any(levels.get(k) is not None for k in ("or_high", "or_low", "pdh", "pdl", "vwap"))
    )
    atr_wired = atr14 is not None
    anchor_missing = not levels_wired and not atr_wired
    cap = cfg.STRUCTURE_SCORE_CAP_ANCHOR_MISSING if anchor_missing else None
    return {
        "levels_available": levels_wired,
        "atr14_available": atr_wired,
        "structure_anchor_missing": anchor_missing,
        "score_cap": cap,
        "note": (
            "PREMARKET v0: levels=null, atr14=null — scores.structure must be null or "
            f"≤{cap}; node_inferred must include structure_anchor_missing."
            if anchor_missing
            else "Structure anchors present for scoring."
        ),
    }


def _make_candidate_entry(
    *,
    sym: str,
    pack: dict[str, Any],
    gate: dict[str, Any],
    window: Window,
    scan_time: dt.datetime,
    rej_path: Path,
    mandatory: bool,
) -> dict[str, Any]:
    best = pack["best"]
    spot = float(best.get("spot") or 0)
    score = float(best.get("score") or 0)
    kill = str(best.get("kill_rule") or "?")
    liq_meta = gate.get("liquidity_meta") or {}
    chain = [_chain_leg(r, scan_time=scan_time) for r in pack["chain_summary_rows"]]
    iv_ctx = build_iv_context(best)
    levels_block = None if window == "PREMARKET" else {
        "or_high": None,
        "or_low": None,
        "pdh": None,
        "pdl": None,
        "vwap": None,
        "note": "EXECUTION levels not wired — intraday module pending",
    }
    struct_ctx = _structure_context(window=window, levels=levels_block, atr14=None)
    why = (
        f"mandatory minimum pick — off-pool score={score:.2f} "
        f"stage1_eligible={gate.get('eligible')} primary_kill={kill}"
        if mandatory
        else f"off-pool BFS near-miss score={score:.2f} primary_kill={kill}"
    )
    entry: dict[str, Any] = {
        "ticker": sym,
        "why_surfaced": why,
        "best_score": round(score, 2),
        "quote": {"last": spot, "asof": scan_time.isoformat()},
        "quote_freshness": {
            "scan_time": scan_time.isoformat(),
            "scan_id": str(best.get("scan_id") or rej_path.stem),
            "quote_source": str(best.get("quote_source") or "indicative"),
            "oi_source": str(best.get("oi_source") or ""),
            "staleness_policy": "scan_batch_age",
            "age_minutes": gate.get("quote_age_minutes"),
        },
        "levels": levels_block,
        "atr14": None,
        "structure_context": struct_ctx,
        "iv_context": iv_ctx,
        "liquidity_context": _liquidity_context(best, liq_meta),
        "chain_summary": chain,
        "event_lane": bool(gate.get("event_lane")),
        "gate_pass": gate.get("gate_pass") or [],
        "gate_reject": gate.get("gate_reject") or [],
    }
    if mandatory:
        entry["mandatory_pick"] = True
    return entry


def build_payload(
    *,
    window: Window = "PREMARKET",
    trade_date: dt.date | None = None,
    rejection_path: Path | None = None,
    now: dt.datetime | None = None,
    staleness_anchor: Literal["now", "scan_plus"] = "now",
) -> Payload:
    """Build coach payload from latest (or dated) rejection log."""
    now = now or dt.datetime.now(EST)
    trade_date = trade_date or now.date()
    dkey = trade_date.isoformat()

    from pool_config import pool_symbols_set

    pool_syms = pool_symbols_set()
    rej_path = rejection_path or latest_rejection_log(trade_date=dkey)
    notes: list[str] = []

    if rej_path is None or not rej_path.is_file():
        raise FileNotFoundError(f"no rejection log for {dkey}")

    scan_time = _parse_scan_time_from_path(rej_path)
    if staleness_anchor == "scan_plus":
        eval_now = scan_time + dt.timedelta(minutes=2)
    else:
        eval_now = now or dt.datetime.now(EST)
        if eval_now <= scan_time:
            eval_now = scan_time + dt.timedelta(minutes=2)
    rows = _load_rejection_rows(rej_path)
    grouped = _best_contracts_by_symbol(rows, pool_syms)

    candidates: list[dict[str, Any]] = []
    for sym in sorted(grouped, key=lambda s: -float(grouped[s]["best"].get("score") or 0)):
        pack = grouped[sym]
        best = pack["best"]
        gate = apply_stage1(sym, best, scan_time=scan_time, today=trade_date, now=eval_now)
        if not gate["eligible"]:
            continue
        candidates.append(
            _make_candidate_entry(
                sym=sym, pack=pack, gate=gate, window=window,
                scan_time=scan_time, rej_path=rej_path, mandatory=False,
            )
        )
        if len(candidates) >= cfg.STAGE1_MAX:
            break

    if staleness_anchor == "scan_plus":
        notes.append("staleness_anchor=scan_plus — replay at scan_time+2m; live runs use anchor=now")
    first_oi = str(rows[0].get("oi_source") or "") if rows else ""
    if first_oi in ("missing_in_snapshot", "missing"):
        notes.append(
            "Alpaca indicative: OI unavailable — stage1 liquidity gate degrades to spread_pct only; "
            "liquidity_context.oi_unverified=true on all candidates"
        )
    notes.append(
        "chain_summary.kill_rules are INFORMATIONAL scan wounds — see schema_semantics.kill_rules"
    )

    if len(candidates) < cfg.MIN_COACH_PICKS_PER_WINDOW:
        seen = {str(c.get("ticker") or "").upper() for c in candidates}
        # O8: only add ELIGIBLE symbols as mandatory picks. Previously stage1-rejected
        # symbols (eligible=False) were forced in to meet MIN_COACH_PICKS_PER_WINDOW —
        # surfacing ineligible picks as if they passed. Now skip ineligible; if none
        # remain eligible, candidates stay short rather than forcing bad picks.
        for sym in sorted(grouped, key=lambda s: -float(grouped[s]["best"].get("score") or 0)):
            if sym in seen:
                continue
            pack = grouped[sym]
            gate = apply_stage1(sym, pack["best"], scan_time=scan_time, today=trade_date, now=eval_now)
            if not gate.get("eligible"):
                notes.append(f"mandatory_pick_skip:{sym} stage1_ineligible ({','.join(gate.get('gate_reject', []))})")
                continue
            candidates.append(
                _make_candidate_entry(
                    sym=sym, pack=pack, gate=gate, window=window,
                    scan_time=scan_time, rej_path=rej_path, mandatory=True,
                )
            )
            notes.append(f"mandatory_pick:{sym} stage1_eligible=True")
            seen.add(sym)
            if len(candidates) >= cfg.MIN_COACH_PICKS_PER_WINDOW:
                break
        if len(candidates) < cfg.MIN_COACH_PICKS_PER_WINDOW:
            off_rows = sorted(
                [r for r in rows if str(r.get("symbol") or "").upper() not in pool_syms],
                key=lambda r: -float(r.get("score") or 0),
            )
            for best in off_rows:
                sym = str(best.get("symbol") or "").upper()
                if not sym or sym in seen:
                    continue
                pack = {"best": best, "chain_summary_rows": [best]}
                grouped[sym] = pack
                gate = apply_stage1(sym, best, scan_time=scan_time, today=trade_date, now=eval_now)
                if not gate.get("eligible"):
                    notes.append(f"mandatory_pick_rescue_skip:{sym} stage1_ineligible")
                    continue
                candidates.append(
                    _make_candidate_entry(
                        sym=sym, pack=pack, gate=gate, window=window,
                        scan_time=scan_time, rej_path=rej_path, mandatory=True,
                    )
                )
                notes.append(f"mandatory_pick_rescue:{sym} stage1_eligible=True")
                seen.add(sym)
                if len(candidates) >= cfg.MIN_COACH_PICKS_PER_WINDOW:
                    break
            if len(candidates) < cfg.MIN_COACH_PICKS_PER_WINDOW:
                notes.append(
                    f"mandatory_pick_exhausted: only {len(candidates)} eligible (< MIN={cfg.MIN_COACH_PICKS_PER_WINDOW}); "
                    "ineligible symbols not forced (O8)"
                )

    payload: Payload = {
        "schema_version": SCHEMA_VERSION,
        "window": window,
        "generated_at": now.isoformat(),
        "trade_date": dkey,
        "scan_provenance": {
            "rejection_log": str(rej_path),
            "scan_time": scan_time.isoformat(),
            "scan_id": str(rows[0].get("scan_id") if rows else ""),
            "row_count": len(rows),
            "off_pool_symbols": len(grouped),
            "option_feed": "indicative",
        },
        "market_context": {
            "spx_pct": None,
            "vix": None,
            "sector_leaders": [],
            "opening_range_note": None,
            "available": False,
            "note": "index context not wired in v0 builder",
        },
        "candidates": candidates,
        "risk_budget": cfg.risk_budget_block(),
        "builder_notes": notes,
        "schema_semantics": {
            "kill_rules": (
                "informational_scan_wounds_not_coach_gate; "
                "ONTO= cite gamma/delta wounds on legs; "
                "GEV= delta edge wipe on best leg is wounded label not veto"
            ),
            "iv_scan_veto": "scoring_veto_stage4_enforces_max_grade_C",
            "oi_unverified": f"liquidity_blind_zone_scores_liquidity_lte_{cfg.LIQUIDITY_SCORE_CAP_OI_UNVERIFIED}",
            "structure_anchor_missing": (
                f"premarket_v0_levels_unwired_scores_structure_null_or_lte_{cfg.STRUCTURE_SCORE_CAP_ANCHOR_MISSING}"
            ),
        },
    }
    return payload


def write_sample(path: Path, payload: Payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
