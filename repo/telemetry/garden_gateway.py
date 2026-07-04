"""Garden → Grid Sovereign Gateway (LM Studio 9B @ :8501). Stdlib only."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

GATEWAY_URL = os.environ.get("GARDEN_GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
_GATEWAY_TIMEOUT = float(os.environ.get("GARDEN_GATEWAY_TIMEOUT", "120"))


def gateway_reachable(timeout: float = 2.5) -> bool:
    try:
        req = urllib.request.Request(f"{GATEWAY_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def gateway_health() -> dict | None:
    try:
        with urllib.request.urlopen(f"{GATEWAY_URL}/health", timeout=2.5) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def sanitize_for_speech(text: str, *, max_len: int = 220) -> str:
    """Strip Qwen 3.5 reasoning blocks; keep a short spoken line for TTS."""
    t = (text or "").strip()
    if not t:
        return t
    if "Thinking Process:" in t or "thinking process" in t.lower():
        quoted = re.findall(r'"([^"]{1,140})"', t)
        if quoted:
            return quoted[-1][:max_len]
        lines = [
            ln.strip(" *-\t")
            for ln in t.splitlines()
            if ln.strip() and "Thinking Process" not in ln and not ln.strip().startswith("*")
        ]
        for ln in reversed(lines):
            if len(ln) > 8 and not ln.endswith(":"):
                return ln[:max_len]
    return t[:max_len]


def gateway_chat(prompt: str, *, user_id: str = "garden", model_hint: str = "auto") -> str | None:
    """POST /gateway → assistant text. Uses computed_verdict; draft_only is not presence evidence."""
    body = json.dumps(
        {"prompt": prompt, "user_id": user_id, "model_hint": model_hint},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{GATEWAY_URL}/gateway",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_GATEWAY_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    text = data.get("response")
    if text is None:
        return None
    cleaned = sanitize_for_speech(str(text).strip())
    return cleaned or None
