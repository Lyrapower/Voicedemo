"""Emit Aether events to gateway /store/events for mobile app (aether.html).

================================================================================
CHANGELOG
--------------------------------------------------------------------------------
v2 (2026-07-24, Fable/守恒 · per FABLE_BFS_SP500_UI_SPEC.md 需求 #4/#5)
  - _scan_rows(): 每行在保留原有 sym/score/note/dir/flag/src 的基础上,
    附加候选 dict 中已有的完整期权字段(字段名与 aether_dryrun 候选 dict
    逐字一致,不做改名翻译):underlying_price, underlying_price_source,
    strike, expiry, dte, delta, gamma_theta_ratio, iv, iv_source, hv_rank,
    iv_hv_ratio, bid, ask, volume, open_interest, spread_pct,
    premium_dollars, price_source, score_breakdown, tags。
    缺失字段直接省略(不写 null),旧消费方不受影响。
  - emit_scan(): payload 增加 "date"(ET 交易日 YYYY-MM-DD)与
    "window"("AM" = ET 12:00 前 / "PM" = 之后),供 UI 按 日期+窗口 分组,
    避免 UTC 跨日误判。仅新增键,原有键与形状不变。
  - 新增 stdlib import: datetime, zoneinfo。无新第三方依赖。
  - 扫描逻辑零改动;本文件仅 emit 层。其余函数逐行照搬 v1。
v1 (原版) — 初始版本。
================================================================================
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

GRID_EVENTS = os.getenv("GRID_EVENTS", "http://127.0.0.1:8501/store/events")

_ET = ZoneInfo("America/New_York")


def emit_aether(kind: str, payload: dict[str, Any]) -> bool:
    """kind: aether_brief | aether_scan | aether_filter | aether_momentum | aether_offpool | aether_offpool_coach"""
    if kind == "aether_scan":
        payload = dict(payload)
        now_et = _dt.datetime.now(_ET)
        payload.setdefault("date", now_et.strftime("%Y-%m-%d"))
        payload.setdefault("window", "AM" if now_et.hour < 12 else "PM")
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
    last_exc: Exception | None = None
    emit_timeout = float(os.getenv("GRID_EMIT_TIMEOUT", "20"))
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=emit_timeout) as resp:
                if 200 <= resp.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(0.75)
    logger.warning("grid emit %s failed: %s", kind, last_exc)
    return False


def store_has_aether_event(kind: str, *, trade_date: str, window: str | None = None) -> bool:
    """True if grid_store already has matching aether event (for emit backfill)."""
    from store_query import store_query_one

    if window:
        row = store_query_one(
            "SELECT id FROM events WHERE source='aether' AND kind=? "
            "AND json_extract(payload, '$.date')=? AND json_extract(payload, '$.window')=? "
            "ORDER BY id DESC LIMIT 1",
            (kind, trade_date, window),
        )
    else:
        row = store_query_one(
            "SELECT id FROM events WHERE source='aether' AND kind=? "
            "AND json_extract(payload, '$.date')=? ORDER BY id DESC LIMIT 1",
            (kind, trade_date),
        )
    return row is not None


# v2: candidate dict 中逐字段透传的键(与 aether_dryrun 候选 dict / format_message 逐字一致)
_FULL_SCAN_KEYS = (
    "underlying_price",
    "underlying_price_source",
    "strike",
    "expiry",
    "dte",
    "delta",
    "gamma_theta_ratio",
    "iv",
    "iv_source",
    "hv_rank",
    "iv_hv_ratio",
    "bid",
    "ask",
    "volume",
    "open_interest",
    "oi_source",
    "oi_unverified",
    "spread_pct",
    "premium_dollars",
    "price_source",
    "score_breakdown",
)


def _candidate_tags(c: dict) -> list[str]:
    """Tags 与 format_message 同源同规则。"""
    tags: list[str] = []
    if c.get("is_perilla"):
        tags.append("紫苏叶")
    if c.get("has_earnings_catalyst"):
        try:
            tags.append(f"财报{c['earnings_days']}天")
        except (KeyError, TypeError):
            tags.append("财报")
    if c.get("has_fda"):
        tags.append("FDA")
    return tags


# Fallback / stale signatures — any candidate whose price/IV came from a fallback
# path (not a live market read) is stamped data_stale=True so downstream UI/LLM
# can distinguish fresh vs degraded data instead of silently treating it as fresh.
_STALE_PRICE_TOKENS = ("last_close", "bs_model", "hv_fallback", "synthetic", "sample")
_STALE_IV_TOKENS = ("hv_fallback", "bs_model", "synthetic")
_STALE_STAGE1_REASONS = ("fallback_rotating_sample",)


def _derive_stale(c: dict) -> tuple[bool, str]:
    """Return (data_stale, data_source) for a candidate dict.

    Looks at price_source / iv_source / stage1_reason / quote_stale / explicit
    data_stale flag set upstream. Conservative: any fallback signal → stale.
    """
    if bool(c.get("data_stale")):
        src = str(c.get("data_source") or "fallback")
        return True, src
    price_src = str(c.get("price_source") or c.get("underlying_price_source") or "")
    iv_src = str(c.get("iv_source") or "")
    stage1 = str(c.get("stage1_reason") or "")
    provider = str(c.get("option_data_provider") or c.get("stock_data_provider") or "")
    quote_stale = bool(c.get("quote_stale"))
    price_stale = bool(c.get("price_stale"))
    iv_stale = bool(c.get("iv_stale"))  # O10: yfinance hv_fallback contracts
    stale = (
        any(tok in price_src for tok in _STALE_PRICE_TOKENS)
        or any(tok in iv_src for tok in _STALE_IV_TOKENS)
        or stage1 in _STALE_STAGE1_REASONS
        or quote_stale
        or price_stale
        or iv_stale
    )
    # Compose a human-readable source string from the most specific signal.
    parts = []
    if price_src:
        parts.append(price_src)
    if iv_src and iv_src != price_src:
        parts.append(iv_src)
    if stage1 and stage1 not in ("", "catalyst_priority"):
        parts.append(stage1)
    if not parts:
        parts.append(provider or "scan")
    return stale, "|".join(parts)


def _scan_rows(candidates: list[dict], *, limit: int = 15) -> list[dict]:
    rows: list[dict] = []
    for c in candidates[:limit]:
        sym = str(c.get("symbol") or "").upper()
        if not sym:
            continue
        prov = str(c.get("option_data_provider") or c.get("stock_data_provider") or "")
        src = "ind" if "indic" in prov.lower() else "rt"
        note_parts = []
        if c.get("delta") is not None:
            note_parts.append(f"Δ={c.get('delta')}")
        if c.get("iv") is not None:
            note_parts.append(f"IV={c.get('iv')}")
        if c.get("spread_pct") is not None:
            note_parts.append(f"spread={float(c['spread_pct']):.1%}")
        if c.get("scan_mode"):
            note_parts.append(str(c["scan_mode"]))
        row = {
            "sym": sym,
            "score": round(float(c.get("score") or 0), 2),
            "note": " · ".join(note_parts) or "scan hit",
            "dir": 1 if float(c.get("score") or 0) >= 50 else -1 if float(c.get("score") or 0) < 35 else 0,
            "flag": bool(c.get("is_perilla") or c.get("has_fda")),
            "src": src,
        }
        # H9: dir above is a quant-score heuristic (>=50 long, <35 short), not a
        # model output. Stamp dir_source so the UI/consumer never mistakes it for
        # a model direction call. If upstream set an explicit model dir, honor it.
        if c.get("dir") is not None and c.get("dir_source"):
            row["dir"] = c.get("dir")
            row["dir_source"] = c.get("dir_source")
        else:
            row["dir_source"] = "heuristic_score"
        # data_stale / data_source: emit-layer flag so downstream never silently
        # treats fallback (hist close / hv_fallback / bs_model / rotating sample)
        # as fresh market data. See _derive_stale for the signal set.
        stale, data_source = _derive_stale(c)
        row["data_stale"] = stale
        row["data_source"] = data_source
        # v2: 透传完整期权字段(仅在候选 dict 中实际存在且非 None 时写入)
        # open_interest 例外:缺 OI 必须写 null,禁止省略后被下游当成 0。
        for key in _FULL_SCAN_KEYS:
            if key not in c:
                continue
            val = c[key]
            if val is None and key != "open_interest":
                continue
            row[key] = val
        tags = _candidate_tags(c)
        if tags:
            row["tags"] = tags
        rows.append(row)
    return rows


def emit_scan(
    candidates: list[dict],
    *,
    label: str = "SCAN",
    universe_size: int | None = None,
    status: str = "ok",
) -> bool:
    now_et = _dt.datetime.now(_ET)
    rows = _scan_rows(candidates)
    any_stale = any(bool(r.get("data_stale")) for r in rows)
    # Aggregate the distinct fallback sources so the UI can show "3 stale · hv_fallback"
    # without walking every row. Empty list when all rows are fresh.
    stale_sources = sorted({str(r.get("data_source")) for r in rows if r.get("data_stale")})
    payload: dict[str, Any] = {
        "label": label,
        "rows": rows,
        "status": status,
        # v2: ET 日期 + AM/PM 窗口,供 UI 按 日期+窗口 分组(避免 UTC 跨日误判)
        "date": now_et.strftime("%Y-%m-%d"),
        "window": "AM" if now_et.hour < 12 else "PM",
        # data_stale / data_source: top-level summary so consumers can gate on it
        # without iterating rows. True iff any candidate used a fallback path.
        "data_stale": any_stale,
        "data_source": "|".join(stale_sources) if any_stale else "scan",
    }
    if universe_size is not None:
        payload["universe_size"] = universe_size
    return emit_aether("aether_scan", payload)


def emit_filter(summary: dict[str, Any] | None) -> bool:
    if not summary or not summary.get("kill_counts"):
        return False
    payload = {
        "scan_id": summary.get("scan_id"),
        "kill_counts": summary.get("kill_counts") or {},
        "near_miss_top": summary.get("near_miss_top") or [],
    }
    return emit_aether("aether_filter", payload)


def emit_momentum(rows: list[dict], *, label: str = "异动") -> bool:
    clean = [
        r for r in (rows or [])
        if isinstance(r, dict) and str(r.get("sym") or "").strip() and str(r.get("note") or "").strip()
    ]
    if not clean:
        return False
    return emit_aether("aether_momentum", {"label": label, "rows": clean})


def emit_offpool(
    *,
    trade_date: str = "",
    items: list[dict],
    model: str = "sonnet-4.6",
    lane: str = "",
    label: str = "",
    cli_model: str = "",
    resolved_models: list[str] | None = None,
    stats: dict[str, Any] | None = None,
    raw: str = "",
) -> bool:
    """CC CLI off-pool top3 — report-only, never merged into Grid compile."""
    lane_key = lane or model
    payload: dict[str, Any] = {
        "model": model,
        "lane": lane_key,
        "label": label or model,
        "cli_model": cli_model,
        "resolved_models": resolved_models or [],
        "items": items,
        "stats": stats or {},
        "raw": raw[:2000] if raw else "",
    }
    if trade_date:
        payload["date"] = trade_date
    return emit_aether("aether_offpool", payload)


def _coach_rows(picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pick in picks:
        sym = str(pick.get("ticker") or "").upper()
        if not sym:
            continue
        grade = str(pick.get("grade") or "")
        scores = pick.get("scores") or {}
        note_parts: list[str] = []
        if grade:
            note_parts.append(f"grade {grade}")
        for key in ("structure", "momentum", "liquidity", "iv_environment", "event_risk"):
            if scores.get(key) is not None:
                note_parts.append(f"{key[:3]}={scores[key]}")
        thesis = str(pick.get("thesis") or "").strip()
        if thesis:
            note_parts.append(thesis[:140])
        rows.append(
            {
                "sym": sym,
                "value": grade or "—",
                "note": " · ".join(note_parts) or "coach pick",
                "grade": grade,
                # H5: propagate mechanical flag so UI can banner fallback picks
                # instead of rendering them as model verdicts.
                "mechanical": bool(pick.get("mechanical")),
                "verdict_source": pick.get("verdict_source"),
            }
        )
    return rows


def emit_offpool_coach(
    *,
    trade_date: str,
    window: str,
    picks: list[dict[str, Any]],
    pick_count: int | None = None,
    verdict_source: str | None = None,
    candidates: int | None = None,
    gated_ok: bool | None = None,
    model: str = "fable",
) -> bool:
    """Fable off-pool coach trial — one emit per window/day; report-only."""
    n = pick_count if pick_count is not None else len(picks)
    payload: dict[str, Any] = {
        "date": trade_date,
        "window": window,
        "model": model,
        "label": f"Fable coach · {window}",
        "items": _coach_rows(picks),
        "picks": picks,
        "pick_count": n,
        "verdict_source": verdict_source or "fable",
        "stats": {
            "item_count": n,
            "candidates": candidates,
            "gated_ok": gated_ok,
        },
    }
    return emit_aether("aether_offpool_coach", payload)


def _premarket_payload(
    *,
    trade_date: str,
    items: list[dict],
    raw: str,
    chain: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "date": trade_date,
        "chain": chain,
        "items": items,
        "raw": raw[:2000] if raw else "",
    }
    if generated_at:
        payload["generated_at"] = generated_at
    return payload


def emit_premarket_grid(
    *,
    trade_date: str,
    items: list[dict],
    raw: str = "",
    generated_at: str | None = None,
) -> bool:
    return emit_aether("aether_premarket_grid", _premarket_payload(
        trade_date=trade_date, items=items, raw=raw, chain="grid", generated_at=generated_at,
    ))


def emit_premarket_sonnet(
    *,
    trade_date: str,
    items: list[dict],
    raw: str = "",
    generated_at: str | None = None,
) -> bool:
    return emit_aether("aether_premarket_sonnet", _premarket_payload(
        trade_date=trade_date, items=items, raw=raw, chain="sonnet", generated_at=generated_at,
    ))


def emit_premarket_deepseek(
    *,
    trade_date: str,
    window: str,
    window_label: str = "",
    items: list[dict],
    raw: str = "",
    generated_at: str | None = None,
    meta: dict[str, Any] | None = None,
) -> bool:
    payload = _premarket_payload(
        trade_date=trade_date,
        items=items,
        raw=raw,
        chain="deepseek-v4",
        generated_at=generated_at,
    )
    payload["window"] = window
    payload["label"] = window_label or window
    payload["lane"] = "deepseek-v4"
    payload["backend"] = "ollama_cloud"
    if meta:
        payload["stats"] = {
            k: meta[k]
            for k in ("model", "duration_ms", "resolved_models", "thinking_hash", "endpoint")
            if k in meta
        }
    return emit_aether("aether_premarket_deepseek", payload)


def emit_premarket(*, trade_date: str, items: list[dict], raw: str = "") -> bool:
    """Legacy kind — new A/B lanes use emit_premarket_grid / emit_premarket_sonnet."""
    return emit_premarket_grid(trade_date=trade_date, items=items, raw=raw)


def emit_deny(*, reason: str, detail: str, trace_file: str = "") -> bool:
    return emit_aether(
        "deny",
        {"reason": reason, "detail": detail, "trace_file": trace_file},
    )


def emit_brief(
    *,
    trade_date: str,
    title: str,
    body: str,
    items: list[dict] | None = None,
    tier: str | None = None,
    trace_id: str | None = None,
    trace_file: str | None = None,
    trust_credit: bool | None = None,
    rehearsal: bool | None = None,
    run_mode: str | None = None,
    budget_route: str | None = None,
    premarket_ab: dict[str, Any] | None = None,
    fact_pack: dict[str, Any] | None = None,
    deepseek_performance: dict[str, Any] | None = None,
    caliber_proof: dict[str, Any] | None = None,
    dry_run: bool = False,
    data_stale: bool | None = None,
    data_source: str | None = None,
) -> bool:
    payload: dict[str, Any] = {
        "date": trade_date,
        "title": title,
        "body": body,
        "items": items or [],
    }
    # data_stale / data_source: when caller passes them explicitly use that;
    # otherwise infer from items (any item with cached=True or data_stale=True).
    if data_stale is None:
        data_stale = any(
            bool(it.get("cached")) or bool(it.get("data_stale"))
            for it in (items or [])
            if isinstance(it, dict)
        )
    if data_source is None:
        srcs = sorted({
            str(it.get("src") or it.get("data_source") or "")
            for it in (items or [])
            if isinstance(it, dict) and (it.get("cached") or it.get("data_stale"))
        })
        data_source = "|".join(s for s in srcs if s) or ("cache" if data_stale else "scan")
    payload["data_stale"] = data_stale
    payload["data_source"] = data_source
    if tier:
        payload["tier"] = tier
    if trace_id:
        payload["trace_id"] = trace_id
    if trace_file:
        payload["trace_file"] = trace_file
    if trust_credit is not None:
        payload["trust_credit"] = trust_credit
    if rehearsal is not None:
        payload["rehearsal"] = rehearsal
    if run_mode:
        payload["run_mode"] = run_mode
    if budget_route:
        payload["budget_route"] = budget_route
    if premarket_ab:
        payload["premarket_ab"] = premarket_ab
    if fact_pack:
        payload["fact_pack"] = fact_pack
    if deepseek_performance:
        payload["deepseek_performance"] = deepseek_performance
    if caliber_proof:
        payload["caliber_proof"] = caliber_proof
    if dry_run:
        payload["dry_run"] = True
    kind = "aether_brief_dryrun" if dry_run else "aether_brief"
    return emit_aether(kind, payload)


def emit_sonnet_earnings(*, trade_date: str, item: dict[str, Any] | None, meta: dict[str, Any] | None = None) -> bool:
    payload: dict[str, Any] = {
        "date": trade_date,
        "item": item,
        "meta": meta or {},
        "lane": "sonnet-earnings",
        "owner": "sonnet",
        "asset_class": "equity_options",
    }
    return emit_aether("aether_sonnet_earnings", payload)


from earnings_integrity import sanitize_anomaly_flag  # noqa: E402


def _anomaly_item(flag: str, *, trade_date: str | None = None) -> dict[str, Any] | None:
    text = sanitize_anomaly_flag(flag)
    if not text:
        return None
    item: dict[str, Any] = {
        "sym": "—",
        "label": "anomaly",
        "value": text,
        "note": "",
        "dir": -1,
        "kind": "integrity_flag",
    }
    if trade_date:
        item["data_date"] = trade_date
    return item


def brief_items_from_final(final: dict[str, Any], *, trade_date: str | None = None) -> list[dict]:
    items: list[dict] = []
    stale = not final.get("scan_valid", True) or bool(final.get("stale_candidates"))
    cache_date = str(final.get("candidate_cache_date") or final.get("scan_date") or "")
    candidate_source = str(final.get("candidate_source") or "cache")
    if stale:
        for row in final.get("stale_candidates") or []:
            note = row.get("note", "缓存候选")
            if cache_date and "[cached" not in note:
                note = f"[cached · {cache_date}] {note}"
            items.append(
                {
                    "sym": row.get("sym", ""),
                    "label": row.get("label", "score"),
                    "value": str(row.get("value", "")),
                    "note": note,
                    "dir": row.get("dir", 0),
                    "src": candidate_source,
                    "cached": True,
                    "data_date": cache_date or None,
                }
            )
        if not items and final.get("top_symbol"):
            note = "缓存候选"
            if cache_date:
                note = f"[cached · {cache_date}] {note}"
            items.append(
                {
                    "sym": str(final.get("top_symbol") or "").strip().upper(),
                    "label": "top_score",
                    "value": str(final.get("top_score", "")),
                    "note": note,
                    "dir": 1,
                    "src": candidate_source,
                    "cached": True,
                    "data_date": cache_date or None,
                }
            )
        items.append(
            {
                "sym": "—",
                "label": "flag",
                "value": "候选来自缓存,非本次扫描产出",
                "note": f"[cached · {cache_date}]" if cache_date else "source",
                "dir": -1,
                "cached": True,
                "data_date": cache_date or None,
            }
        )
        for flag in dict.fromkeys(final.get("anomaly_flags") or []):
            if _integrity_flag_for_display(flag):
                it = _anomaly_item(str(flag), trade_date=trade_date)
                if it:
                    items.append(it)
        return items

    sym = str(final.get("top_symbol") or "").strip().upper()
    if sym:
        items.append(
            {
                "sym": sym,
                "label": "top_score",
                "value": str(final.get("top_score", "")),
                "note": "盘后",
                "dir": 1,
                "src": "scan",
            }
        )
    for flag in dict.fromkeys(final.get("anomaly_flags") or []):
        it = _anomaly_item(str(flag), trade_date=trade_date)
        if it:
            items.append(it)
    return items


def _integrity_flag_for_display(flag: str) -> bool:
    upper = str(flag).upper()
    tokens = (
        "SCAN_ABORTED",
        "UNIVERSE_EMPTY",
        "SP500_UNIVERSE_EMPTY",
        "SSL",
    )
    return any(token in upper for token in tokens)
