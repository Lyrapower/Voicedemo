"""LM Studio OpenAI-compatible local inference (no cloud API)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def call_lmstudio(
    messages: list[dict[str, Any]],
    *,
    base_url: str,
    model: str,
    timeout_s: float = 300.0,
    metadata: dict[str, Any] | None = None,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "stream": False,
    }
    if metadata:
        payload["user"] = str(metadata.get("session_id", ""))[:64]

    from lm_studio_auth import lm_auth_headers

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=lm_auth_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"LM Studio HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"LM Studio unreachable at {url} — load qwen3-14b-mlx in LM Studio first"
        ) from e

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError(f"LM Studio empty choices: {body!r:.400}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise RuntimeError("LM Studio returned empty content")
    return str(content).strip()
