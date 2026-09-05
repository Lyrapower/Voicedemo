"""Tests for Kimi K2.6 API-equivalent pricing."""
from code_task.kimi_k25_pricing import (
    KIMI_K25_INPUT_USD_PER_M,
    KIMI_K25_OUTPUT_USD_PER_M,
    enrich_kimi_usage,
    estimate_kimi_k25_cost_usd,
)


def test_estimate_from_ollama_fields():
    usage = {"prompt_eval_count": 1000, "eval_count": 500}
    cost = estimate_kimi_k25_cost_usd(usage)
    expected = (1000 * KIMI_K25_INPUT_USD_PER_M + 500 * KIMI_K25_OUTPUT_USD_PER_M) / 1_000_000
    assert cost == expected


def test_estimate_from_openai_fields():
    usage = {"prompt_tokens": 2_000_000, "completion_tokens": 1_000_000}
    cost = estimate_kimi_k25_cost_usd(usage)
    assert cost == 2 * KIMI_K25_INPUT_USD_PER_M + 1 * KIMI_K25_OUTPUT_USD_PER_M


def test_enrich_adds_metadata():
    out = enrich_kimi_usage({"prompt_tokens": 100, "completion_tokens": 50})
    assert out["billing"] == "api"
    assert out["cost_model"] == "kimi-k2.6"
    assert out["cost_usd"] > 0
