#!/usr/bin/env python3
"""Capture before/after token budget samples → traces/proof/token_budget_report.json."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "traces" / "proof"
REPORT = PROOF / "token_budget_report.json"
BASE = "http://127.0.0.1:8501"

BEFORE_BASELINE = [
    {"route": "chat", "max_tokens": 128, "reasoning_tokens": 127, "content_tokens": 0, "finish_reason": "length", "note": "LM Studio tab pre-deploy"},
    {"route": "chat", "max_tokens": 128, "reasoning_tokens": 127, "content_tokens": 0, "finish_reason": "length", "note": "LM Studio tab pre-deploy"},
    {"route": "gateway", "max_tokens": 2048, "reasoning_tokens": 511, "content_tokens": 12, "finish_reason": "length", "note": "gateway pre-V4.11"},
    {"route": "compile", "max_tokens": 256, "reasoning_tokens": 200, "content_tokens": 0, "finish_reason": "length", "note": "compile NULL era"},
    {"route": "chat", "max_tokens": 2048, "reasoning_tokens": 1800, "content_tokens": 200, "finish_reason": "stop", "note": "白皮书化 — budget too high"},
]

SAMPLES = [
    ("compile", "POST", "/compile", {"signal": "compile intent: list two verification steps only, JSON ast."}),
    ("compile", "POST", "/compile", {"signal": "signal: verify grid compile path returns structured output"}),
    ("gateway", "POST", "/gateway", {"prompt": "Summarize gateway role in two sentences."}),
    ("chat", "POST", "/v1/chat/completions", {
        "messages": [{"role": "user", "content": "用三句话介绍 Grid Sovereign Gateway。"}],
        "max_tokens": 400,
    }),
    ("chat", "POST", "/v1/chat/completions", {
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    }),
]


def post_json(path: str, body: dict, *, timeout: float = 120.0) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def sample_row(route: str, body: dict, resp: dict) -> dict:
    usage = resp.get("substrate_usage") or resp.get("grid_meta", {}).get("substrate_usage") or {}
    if not usage and resp.get("usage"):
        det = resp["usage"].get("completion_tokens_details") or {}
        comp = int(resp["usage"].get("completion_tokens") or 0)
        reasoning = int(det.get("reasoning_tokens") or 0)
        usage = {
            "completion_tokens": comp,
            "reasoning_tokens": reasoning,
            "content_tokens": max(0, comp - reasoning),
        }
    fr = resp.get("upstream_finish_reason")
    if not fr and resp.get("choices"):
        fr = resp["choices"][0].get("finish_reason")
    if not fr:
        fr = usage.get("finish_reason") or ("length" if resp.get("truncated") else "unknown")
    max_sent = resp.get("grid_meta", {}).get("max_tokens_sent") or body.get("max_tokens")
    return {
        "route": route,
        "max_tokens": max_sent,
        "reasoning_tokens": int(usage.get("reasoning_tokens") or 0),
        "content_tokens": int(usage.get("content_tokens") or 0),
        "finish_reason": str(fr),
        "truncated": bool(resp.get("truncated") or fr == "length"),
    }


def main() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from ensure_gateway_up import ensure_gateway_up

    health = ensure_gateway_up(BASE, timeout=30.0)
    budget = health.get("budget") or {}

    after: list[dict] = []
    for route, method, path, body in SAMPLES:
        try:
            resp = post_json(path, body)
            after.append(sample_row(route, body, resp))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            after.append({"route": route, "error": str(e)})
        time.sleep(0.3)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget_config": budget,
        "before_baseline": BEFORE_BASELINE,
        "after_samples": after,
    }
    PROOF.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nWrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
