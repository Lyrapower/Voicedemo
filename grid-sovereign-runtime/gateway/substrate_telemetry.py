"""Substrate token telemetry — per-route buckets, alert on waterline breach."""
from __future__ import annotations

import difflib
import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger("grid.gateway.telemetry")

# chat path waterlines (work order §4)
CHAT_TRUNCATION_WARN = 0.05
CHAT_REASONING_TAX_WARN = 0.3
REPETITION_DIFF_THRESHOLD = 0.90  # diff_rate > 90% ⇒ REPETITION_FLAG

_buckets: dict[str, list[dict]] = defaultdict(list)
_repetition_flag_count = 0
_repetition_samples: list[dict] = []
_MAX_SAMPLES = 500


def text_diff_rate(a: str, b: str) -> float:
    """0 = identical, 1 = completely different."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a and not b:
        return 0.0
    if a == b:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


def check_repetition_pair(
    *,
    prompt: str,
    text_a: str,
    text_b: str,
    route: str = "unknown",
) -> dict[str, Any]:
    """Same prompt twin-fire: diff_rate > 90% similarity ⇒ REPETITION_FLAG."""
    global _repetition_flag_count
    diff_rate = text_diff_rate(text_a, text_b)
    similarity = 1.0 - diff_rate
    flagged = similarity > REPETITION_DIFF_THRESHOLD
    row = {
        "ts": time.time(),
        "route": route,
        "prompt_preview": (prompt or "")[:120],
        "diff_rate": round(diff_rate, 4),
        "similarity": round(similarity, 4),
        "repetition_flag": flagged,
        "len_a": len(text_a or ""),
        "len_b": len(text_b or ""),
    }
    if flagged:
        _repetition_flag_count += 1
        _repetition_samples.append(row)
        if len(_repetition_samples) > 50:
            del _repetition_samples[: len(_repetition_samples) - 50]
        logger.warning(
            "REPETITION_FLAG route=%s similarity=%.3f prompt=%r",
            route, similarity, row["prompt_preview"],
        )
    return row


def record_request(
    *,
    route: str,
    max_tokens: int,
    usage: dict | None,
    finish_reason: str | None = None,
    gate_reason: str | None = None,
) -> None:
    u = usage or {}
    fr = finish_reason or u.get("finish_reason") or "unknown"
    completion = int(u.get("completion_tokens") or 0)
    reasoning = int(u.get("reasoning_tokens") or 0)
    content = int(u.get("content_tokens") or max(0, completion - reasoning))
    gr = (gate_reason or "").strip()
    entry = {
        "ts": time.time(),
        "route": route,
        "max_tokens": max_tokens,
        "reasoning_tokens": reasoning,
        "content_tokens": content,
        "completion_tokens": completion,
        "finish_reason": fr,
        "truncated": fr == "length",
        "empty_after_sanitize": gr == "empty_after_sanitize",
        "gate_reason": gr or None,
        "reasoning_tax": round(reasoning / completion, 4) if completion else 0.0,
    }
    bucket = _buckets[route]
    bucket.append(entry)
    if len(bucket) > _MAX_SAMPLES:
        del bucket[: len(bucket) - _MAX_SAMPLES]
    _maybe_alert(route)


def _aggregate(route: str) -> dict[str, Any]:
    rows = _buckets.get(route) or []
    if not rows:
        return {"count": 0}
    n = len(rows)
    truncated = sum(1 for r in rows if r["truncated"])
    empty_san = sum(1 for r in rows if r.get("empty_after_sanitize"))
    taxes = [r["reasoning_tax"] for r in rows if r["completion_tokens"]]
    return {
        "count": n,
        "truncation_rate": round(truncated / n, 4),
        "truncation_count": truncated,
        "empty_after_sanitize_rate": round(empty_san / n, 4),
        "empty_after_sanitize_count": empty_san,
        "reasoning_tax_mean": round(sum(taxes) / len(taxes), 4) if taxes else 0.0,
        "avg_reasoning_tokens": round(sum(r["reasoning_tokens"] for r in rows) / n, 2),
        "avg_content_tokens": round(sum(r["content_tokens"] for r in rows) / n, 2),
    }


def snapshot() -> dict[str, Any]:
    per_route = {route: _aggregate(route) for route in sorted(_buckets.keys())}
    all_rows = [r for rows in _buckets.values() for r in rows]
    if not all_rows:
        return {
            "routes": per_route,
            "all": {"count": 0},
            "repetition_flag_count": _repetition_flag_count,
            "repetition_samples": list(_repetition_samples[-5:]),
        }
    n = len(all_rows)
    truncated = sum(1 for r in all_rows if r["truncated"])
    empty_san = sum(1 for r in all_rows if r.get("empty_after_sanitize"))
    return {
        "routes": per_route,
        "all": {
            "count": n,
            "truncation_rate": round(truncated / n, 4),
            "empty_after_sanitize_rate": round(empty_san / n, 4),
            "repetition_flag_count": _repetition_flag_count,
        },
        "repetition_flag_count": _repetition_flag_count,
        "repetition_samples": list(_repetition_samples[-5:]),
    }


def _maybe_alert(route: str) -> None:
    if route != "chat":
        return
    agg = _aggregate(route)
    if agg.get("count", 0) < 3:
        return
    tr = agg.get("truncation_rate", 0.0)
    tax = agg.get("reasoning_tax_mean", 0.0)
    if tr > CHAT_TRUNCATION_WARN:
        logger.warning(
            "substrate budget alert: chat truncation_rate=%.3f > %.2f (n=%s)",
            tr, CHAT_TRUNCATION_WARN, agg["count"],
        )
    if tax > CHAT_REASONING_TAX_WARN:
        logger.warning(
            "substrate budget alert: chat reasoning_tax=%.3f > %.2f (n=%s)",
            tax, CHAT_REASONING_TAX_WARN, agg["count"],
        )


def reset() -> None:
    global _repetition_flag_count
    _buckets.clear()
    _repetition_flag_count = 0
    _repetition_samples.clear()
