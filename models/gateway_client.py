"""8787 → :8501 gateway client. All inference via gateway; never direct :1234."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_GATEWAY = os.environ.get("GARDEN_GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
_TIMEOUT = float(os.environ.get("GARDEN_GATEWAY_TIMEOUT", "120"))

# Gateway-computed verdicts — safe to use for routing decisions.
DETERMINISTIC_VERDICTS = frozenset({
    "PREFILTER", "DEEP_ROUTE", "SUBSTRATE_NULL", "BLOCKED",
    "CONTRACT:FAKE_PASS", "CONTRACT:ABSENCE", "CONTRACT:CAPITULATION",
    "CONTRACT:TOOL_DRYRUN", "CONTRACT:REASONING_STRIP", "CONTRACT:REWRITE",
    "NULL", "PASS", "FAIL",
})


def _post(path: str, body: dict, *, timeout: float | None = None) -> dict | None:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{DEFAULT_GATEWAY}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def gateway_dialogue_envelope(prompt: str, *, user_id: str = "8787") -> dict | None:
    """POST /gateway — full envelope with computed_verdict and draft_only."""
    return _post("/gateway", {"prompt": prompt, "user_id": user_id, "model_hint": "auto"})


def gateway_dialogue(prompt: str, *, user_id: str = "8787") -> str | None:
    """POST /gateway — display text only. Check envelope for presence decisions."""
    data = gateway_dialogue_envelope(prompt, user_id=user_id)
    return dialogue_display_text(data)


def dialogue_display_text(data: dict | None) -> str | None:
    if not data:
        return None
    text = data.get("response")
    if text is None:
        return None
    return str(text).strip() or None


def is_presence_safe_envelope(data: dict | None) -> bool:
    """True when response may be treated as non-draft for routing (never for live presence)."""
    if not data:
        return False
    if data.get("draft_only"):
        return False
    cv = str(data.get("computed_verdict") or "")
    if cv.startswith("CONTRACT:") or cv in ("BLOCKED", "SUBSTRATE_NULL", "PREFILTER"):
        return True
    return False


def gateway_compile(signal: str) -> dict | None:
    """POST /compile — dual-channel contract, gateway-computed verdict, draft artifacts."""
    return _post("/compile", {"signal": signal}, timeout=max(_TIMEOUT, 360.0))
