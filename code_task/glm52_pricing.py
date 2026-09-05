"""GLM 5.2 API-equivalent token pricing (Z.ai / OpenRouter list, 2026-07).

Used for Ollama Cloud `glm-5.2:cloud` usage estimates. Ollama Pro subscription
is separate; this is per-token API list pricing for display/telemetry only.
"""
from __future__ import annotations

from typing import Any

# USD per 1M tokens — Z.ai first-party / OpenRouter z-ai/glm-5.2 list
GLM52_INPUT_USD_PER_M = 1.40
GLM52_OUTPUT_USD_PER_M = 4.40


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


def estimate_glm52_cost_usd(usage: dict[str, Any] | None) -> float | None:
    """Estimate API-equivalent USD from Ollama/GLM usage dict."""
    pin, pout = _token_counts(usage)
    if pin <= 0 and pout <= 0:
        return None
    return (pin * GLM52_INPUT_USD_PER_M + pout * GLM52_OUTPUT_USD_PER_M) / 1_000_000


def enrich_glm52_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Add cost_usd + billing metadata when token counts present."""
    out = dict(usage or {})
    cost = estimate_glm52_cost_usd(out)
    if cost is not None:
        out["cost_usd"] = round(cost, 6)
        out["billing"] = "api"
        out["cost_model"] = "glm-5.2"
        out["cost_basis"] = "Z.ai GLM-5.2 list ($1.40/M in · $4.40/M out)"
    return out
