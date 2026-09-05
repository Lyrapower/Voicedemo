"""Ollama Cloud DeepSeek V4 capture for off-pool daemon (stdlib HTTP)."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_MODEL = "deepseek-v4-flash:cloud"
DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/chat"
MIN_NUM_PREDICT = 512


def _extract_thinking(message: dict[str, Any], body: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("thinking", "reasoning_content", "reasoning"):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    for key in ("thinking", "reasoning_content", "reasoning"):
        val = body.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    return "\n".join(parts)


def capture_sync(
    *,
    prompt: str,
    model: str | None = None,
    endpoint: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: float = 300.0,
) -> tuple[str | None, dict[str, Any]]:
    model = (model or os.getenv("OFFPOOL_DEEPSEEK_MODEL") or DEFAULT_MODEL).strip()
    endpoint = (
        endpoint
        or os.getenv("OLLAMA_ENDPOINT")
        or os.getenv("OFFPOOL_OLLAMA_ENDPOINT")
        or DEFAULT_ENDPOINT
    ).strip()
    meta: dict[str, Any] = {
        "backend": "deepseek_v4_cloud",
        "model": model,
        "endpoint": endpoint,
        "resolved_models": [model],
        "cost_usd": None,
        "duration_ms": None,
        "thinking_hash": None,
        "error": None,
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": True,
        "options": {
            "num_predict": max(int(max_tokens), MIN_NUM_PREDICT),
            "temperature": float(temperature),
        },
    }
    started = time.time()
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        meta["error"] = detail or str(exc)
        meta["duration_ms"] = int((time.time() - started) * 1000)
        return None, meta
    except Exception as exc:  # noqa: BLE001
        meta["error"] = str(exc)[:400]
        meta["duration_ms"] = int((time.time() - started) * 1000)
        return None, meta

    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    thinking = _extract_thinking(message, body)
    if thinking:
        meta["thinking_hash"] = hashlib.sha256(thinking.encode("utf-8")).hexdigest()[:16]
    content = str(message.get("content") or "").strip()
    meta["duration_ms"] = int((time.time() - started) * 1000)
    if not content:
        meta["error"] = "empty_content"
        return None, meta
    return content, meta
