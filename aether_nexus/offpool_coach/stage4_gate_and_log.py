"""Stage 4 — schema validation, fabrication sweep, grade gate, jsonl log."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from offpool_coach import config as cfg
from offpool_coach.schema import Payload

_NUM = re.compile(r"-?\d+\.?\d*")
_GRADES = frozenset({"S", "A", "B", "C"})
_SCORE_KEYS = frozenset({"structure", "momentum", "liquidity", "iv_environment", "event_risk"})


def payload_hash(payload: Payload) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _num_forms(value: float | int) -> set[str]:
    forms = {str(value), f"{value:.2f}", f"{value:.4f}", f"{value:.6f}"}
    if isinstance(value, float) and value == int(value):
        forms.add(str(int(value)))
    return forms


def enrich_allowed(payload: Payload, allowed: set[str]) -> set[str]:
    """Add percent/spread/date derivations so thesis may cite iv_pct without false fabrications."""
    for c in payload.get("candidates") or []:
        ivc = c.get("iv_context") or {}
        for k in ("iv", "iv_pct", "scan_max_iv", "scan_max_iv_pct"):
            v = ivc.get(k)
            if v is not None:
                allowed |= _num_forms(float(v))
        iv = ivc.get("iv")
        if iv is not None:
            pct = float(iv) * 100.0
            allowed |= _num_forms(pct)
            allowed |= _num_forms(round(pct, 1))
            allowed |= _num_forms(round(pct, 2))
            allowed.add(str(int(round(pct))))

        liq = c.get("liquidity_context") or {}
        sp = liq.get("spread_pct")
        if sp is not None:
            allowed |= _num_forms(float(sp))
            spct = float(sp) * 100.0
            allowed |= _num_forms(spct)
            allowed |= _num_forms(round(spct, 1))
            allowed |= _num_forms(round(spct, 2))

        for leg in c.get("chain_summary") or []:
            for k in ("strike", "delta", "iv", "spread_pct", "volume", "bid", "ask", "mid"):
                v = leg.get(k)
                if v is not None:
                    allowed |= _num_forms(float(v))
            if leg.get("iv") is not None:
                lp = float(leg["iv"]) * 100.0
                allowed |= _num_forms(round(lp, 1))
                allowed |= _num_forms(round(lp, 2))
            if leg.get("spread_pct") is not None:
                lsp = float(leg["spread_pct"]) * 100.0
                allowed |= _num_forms(round(lsp, 1))
                allowed |= _num_forms(round(lsp, 2))
            for part in re.findall(r"\d+", str(leg.get("exp") or "")):
                allowed.add(part)

        for gp in c.get("gate_pass") or []:
            for m in _NUM.findall(str(gp)):
                allowed.add(m)

        q = c.get("quote") or {}
        if q.get("last") is not None:
            allowed |= _num_forms(float(q["last"]))
        if c.get("best_score") is not None:
            allowed |= _num_forms(float(c["best_score"]))

    return allowed


def allowed_numbers(payload: Payload) -> set[str]:
    """Numeric tokens present in payload (string form for sweep)."""
    allowed: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, bool) or obj is None:
            return
        if isinstance(obj, (int, float)):
            if isinstance(obj, float) and obj == int(obj):
                allowed.add(str(int(obj)))
            allowed.add(str(obj))
            allowed.add(f"{obj:.2f}")
            allowed.add(f"{obj:.4f}")
            allowed.add(f"{obj:.6f}")
            return
        if isinstance(obj, str):
            for m in _NUM.findall(obj):
                allowed.add(m)
            return
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(payload)
    return enrich_allowed(payload, allowed)


def fabrication_violations(json_text: str, payload: Payload) -> list[str]:
    """Strict on scores; thesis numbers checked only for large tokens (strikes/prices)."""
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        return []

    violations: list[str] = []
    if not isinstance(parsed, list):
        return ["violation:expected_json_array"]

    allowed = allowed_numbers(payload)
    skip_small = frozenset(str(i) for i in range(11))

    for item in parsed:
        if not isinstance(item, dict):
            continue
        scores = item.get("scores") or {}
        for k, v in scores.items():
            if v is None:
                if k == "structure":
                    continue
                violations.append(f"score_null:{k}")
                continue
            if not isinstance(v, (int, float)) or v < 0 or v > 10:
                violations.append(f"score:{k}:{v}")

        for field in ("thesis", "falsifier"):
            for m in set(_NUM.findall(str(item.get(field) or ""))):
                if m in skip_small:
                    continue
                if m in allowed:
                    continue
                try:
                    fv = float(m)
                except ValueError:
                    violations.append(m)
                    continue
                # Hard-fail strikes/prices/volumes only — allow rounded IV % and small derived spreads.
                if fv >= 100 or (fv >= 50 and abs(fv - round(fv)) < 1e-9):
                    violations.append(m)

    return violations[:20]


def _candidate_by_ticker(payload: Payload) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for c in payload.get("candidates") or []:
        sym = str(c.get("ticker") or "").upper()
        if sym:
            out[sym] = c
    return out


def _structure_anchor_missing(cand: dict[str, Any]) -> bool:
    sc = cand.get("structure_context") or {}
    if sc.get("structure_anchor_missing") is not None:
        return bool(sc.get("structure_anchor_missing"))
    return cand.get("levels") is None and cand.get("atr14") is None


def _node_inferred_blob(item: dict[str, Any]) -> str:
    inferred = item.get("node_inferred") or []
    return " ".join(str(x) for x in inferred).lower()


def scoring_violations(parsed: Any, payload: Payload) -> list[str]:
    """Enforce iv veto, oi_unverified cap, structure anchor cap on Fable output."""
    expected = len(payload.get("candidates") or [])
    if expected == 0:
        return []

    if not isinstance(parsed, list):
        return ["violation:expected_json_array"]

    if len(parsed) == 0:
        return ["violation:empty_verdict_with_candidates"]

    by_ticker = _candidate_by_ticker(payload)
    violations: list[str] = []

    for item in parsed:
        if not isinstance(item, dict):
            violations.append("violation:item_not_object")
            continue
        sym = str(item.get("ticker") or "").upper()
        cand = by_ticker.get(sym)
        if not cand:
            violations.append(f"violation:unknown_ticker:{sym or '?'}")
            continue

        grade = str(item.get("grade") or "").upper()
        if grade and grade not in _GRADES:
            violations.append(f"violation:bad_grade:{sym}:{grade}")

        scores = item.get("scores") or {}
        if not isinstance(scores, dict):
            violations.append(f"violation:missing_scores:{sym}")
            continue
        missing = _SCORE_KEYS - set(scores.keys())
        if missing:
            violations.append(f"violation:scores_incomplete:{sym}:{','.join(sorted(missing))}")

        iv_ctx = cand.get("iv_context") or {}
        if iv_ctx.get("iv_scan_veto") and grade in ("S", "A"):
            violations.append(f"violation:iv_veto_grade:{sym}:{grade}")

        liq_ctx = cand.get("liquidity_context") or {}
        liq_cap = int(liq_ctx.get("score_cap") or cfg.LIQUIDITY_SCORE_CAP_OI_UNVERIFIED)
        if liq_ctx.get("oi_unverified"):
            blob = _node_inferred_blob(item)
            if "oi_unverified" not in blob and "blind zone" not in blob:
                violations.append(f"violation:oi_unverified_unacknowledged:{sym}")
            liq_score = scores.get("liquidity")
            if liq_score is not None and float(liq_score) > liq_cap:
                violations.append(f"violation:liquidity_cap:{sym}:{liq_score}>{liq_cap}")

        if iv_ctx.get("iv_scan_veto"):
            iv_score = scores.get("iv_environment")
            if iv_score is not None and float(iv_score) > 0:
                violations.append(f"violation:iv_veto_score:{sym}:iv_environment={iv_score}")

        if _structure_anchor_missing(cand):
            struct_cap = int(
                (cand.get("structure_context") or {}).get("score_cap")
                or cfg.STRUCTURE_SCORE_CAP_ANCHOR_MISSING
            )
            blob = _node_inferred_blob(item)
            if "structure_anchor_missing" not in blob:
                violations.append(f"violation:structure_anchor_unacknowledged:{sym}")
            struct_score = scores.get("structure")
            if struct_score is None:
                pass
            elif float(struct_score) > struct_cap:
                violations.append(f"violation:structure_cap:{sym}:{struct_score}>{struct_cap}")

    return violations


def gate_response(raw: str, payload: Payload) -> dict[str, Any]:
    try:
        start = raw.index("[") if "[" in raw else raw.index("{")
        end = raw.rindex("]") + 1 if "[" in raw else raw.rindex("}") + 1
        json_slice = raw[start:end]
        parsed = json.loads(json_slice)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": "violation:bad_json", "detail": str(exc)}

    violations = fabrication_violations(json_slice, payload)
    if violations:
        return {"ok": False, "reason": "violation:fabricated_number", "violations": violations}

    score_v = scoring_violations(parsed, payload)
    if score_v:
        return {"ok": False, "reason": "violation:scoring_contract", "violations": score_v, "parsed": parsed}

    return {"ok": True, "parsed": parsed, "violations": []}


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def log_run(
    *,
    payload: Payload,
    prompt_hash: str,
    raw_response: str,
    gated: dict[str, Any],
    trade_date: str,
    pick_count: int | None = None,
    verdict_source: str | None = None,
) -> Path:
    out_dir = Path(cfg.OUTPUT_DIR)
    path = out_dir / f"{trade_date}.jsonl"
    append_jsonl(
        path,
        {
            "kind": "coach_run",
            "trade_date": trade_date,
            "window": payload.get("window"),
            "payload_hash": payload_hash(payload),
            "prompt_hash": prompt_hash,
            "gated_ok": gated.get("ok"),
            "gated_reason": gated.get("reason"),
            "violations": gated.get("violations"),
            "raw_excerpt": (raw_response or "")[:4000],
            "raw_len": len(raw_response or ""),
            "pick_count": pick_count,
            "verdict_source": verdict_source,
            "parsed_tickers": [
                str(x.get("ticker") or "") for x in (gated.get("parsed") or [])
                if isinstance(x, dict)
            ][: cfg.MIN_COACH_PICKS_PER_WINDOW + 3],
        },
    )
    if raw_response:
        raw_path = out_dir / f"{trade_date}_raw.txt"
        raw_path.write_text(raw_response, encoding="utf-8")
    return path
