"""Fetch FIELD_NOW observer context from :8795 for Grid (demo/aster) inference."""
from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request

from aster_identity import is_aster_model

FIELD_NOW_URL = "http://127.0.0.1:8795/now"
FIELD_NOW_TIMEOUT = 0.8
FIELD_NOW_CACHE_SEC = 25.0

_BLOCK_HEAD = (
    "--- FIELD_NOW (observer-only; authority=none; represents_user_intent=false) ---"
)
_BLOCK_TAIL = "--- END FIELD_NOW ---"

_cache = {"t": 0.0, "text": ""}
_cache_lock = threading.Lock()
_last_fetch_ok = False


def field_now_enabled() -> bool:
    return os.getenv("FIELD_NOW_ENABLED", "1").lower() not in ("0", "false", "no", "off")


def field_now_status() -> dict[str, object]:
    with _cache_lock:
        return {
            "enabled": field_now_enabled(),
            "last_fetch_ok": _last_fetch_ok,
            "cached_chars": len(_cache["text"]),
            "cache_age_sec": max(0.0, time.time() - _cache["t"]) if _cache["t"] else None,
        }


def _fetch_now_plain() -> str:
    global _last_fetch_ok
    req = urllib.request.Request(
        FIELD_NOW_URL,
        headers={"Accept": "text/plain", "User-Agent": "grid-gateway-field-now/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=FIELD_NOW_TIMEOUT) as resp:
            host = getattr(resp, "url", FIELD_NOW_URL)
            if "127.0.0.1" not in str(host) and "localhost" not in str(host):
                _last_fetch_ok = False
                return ""
            raw = resp.read(2048).decode("utf-8", errors="replace").strip()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        _last_fetch_ok = False
        return ""
    if not raw or len(raw) > 1200:
        _last_fetch_ok = False
        return ""
    _last_fetch_ok = True
    return raw


def get_field_now_block() -> str:
    """Cached /now text wrapped as observer-only context; fail-open → empty string."""
    if not field_now_enabled():
        return ""
    now = time.time()
    with _cache_lock:
        if _cache["text"] and now - _cache["t"] <= FIELD_NOW_CACHE_SEC:
            body = _cache["text"]
        else:
            body = _fetch_now_plain()
            if body:
                _cache["text"] = body
                _cache["t"] = now
            else:
                body = _cache["text"] if now - _cache["t"] <= FIELD_NOW_CACHE_SEC * 2 else ""
    if not body:
        return ""
    return "%s\n%s\n%s" % (_BLOCK_HEAD, body, _BLOCK_TAIL)


def append_field_now_observer_context(
    messages: list,
    model: str | None,
    *,
    chain_verified: bool = False,
) -> tuple[list, bool]:
    """
    Append FIELD_NOW block to the first system message for Grid (demo/aster).
    Does not replace Core system prompt. Returns (messages, injected).
    """
    if is_aster_model(model) and not chain_verified:
        from grid_chain_verification import GridVerificationRequired, GridChainVerification

        raise GridVerificationRequired(
            GridChainVerification(
                ok=False,
                reason="field_now injection requires full Grid chain verification",
                missing_layers=["schema", "route", "signer", "keyholder", "hmac"],
            )
        )
    if not is_aster_model(model):
        return messages, False
    if not field_now_enabled():
        return messages, False
    block = get_field_now_block()
    if not block:
        return messages, False
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") != "system":
            continue
        prev = str(m.get("content") or "").rstrip()
        m["content"] = (prev + "\n\n" + block).strip() if prev else block
        return out, True
    out.insert(0, {"role": "system", "content": block})
    return out, True
