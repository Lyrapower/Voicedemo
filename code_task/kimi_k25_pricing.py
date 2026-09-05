"""Kimi K2.6 API-equivalent token pricing (Moonshot platform.kimi.ai, 2026-07).

Used for Ollama Cloud `kimi-k2.6:cloud` usage estimates. Ollama Pro subscription
is separate; this is per-token API list pricing for display/telemetry only.
"""
from __future__ import annotations

from typing import Any

# USD per 1M tokens — platform.kimi.ai K2.6 list (cache-miss input · output)
KIMI_K25_INPUT_USD_PER_M = 0.95
KIMI_K25_OUTPUT_USD_PER_M = 4.00
KIMI_K25_CACHE_INPUT_USD_PER_M = 0.16


def _token_counts(usage: dict[str, Any] | None) -> tuple[int, int]:
    if not usage:
        return 0, 0
    pin = (
        usage.get("prompt_tokens")
        or usage.get("prompt_eval_count")
        or usage.get("input_tokens")
        or 0
    )
    pout = (
        usage.get("completion_tokens")
        or usage.get("eval_count")
        or usage.get("output_tokens")
        or 0
    )
    return int(pin or 0), int(pout or 0)


def estimate_kimi_k25_cost_usd(usage: dict[str, Any] | None) -> float | None:
    """Estimate API-equivalent USD from Ollama/Kimi usage dict."""
    pin, pout = _token_counts(usage)
    if pin <= 0 and pout <= 0:
        return None
    return (pin * KIMI_K25_INPUT_USD_PER_M + pout * KIMI_K25_OUTPUT_USD_PER_M) / 1_000_000


def enrich_kimi_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Add cost_usd + billing metadata when token counts present."""
    out = dict(usage or {})
    cost = estimate_kimi_k25_cost_usd(out)
    if cost is not None:
        out["cost_usd"] = round(cost, 6)
        out["billing"] = "api"
        out["cost_model"] = "kimi-k2.6"
        out["cost_basis"] = "platform.kimi.ai K2.6 list ($0.95/M in · $4/M out)"
    return out
