"""LM Studio OpenAI-compatible API — local inference (no Ollama)."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_SUBSTRATE_SCRIPTS = (
    Path(__file__).resolve().parents[1] / "scripts" / "substrate_airlock" / "scripts"
)
_SUBSTRATE_AIRLOCK = (
    Path(__file__).resolve().parents[1] / "scripts" / "substrate_airlock"
)
if str(_SUBSTRATE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SUBSTRATE_SCRIPTS))
if str(_SUBSTRATE_AIRLOCK) not in sys.path:
    sys.path.insert(0, str(_SUBSTRATE_AIRLOCK))
from airlock_bridge import process_lm_studio_body  # noqa: E402


def _defaults_from_aster() -> tuple[str, str, float, int]:
    try:
        from .aster_config import (
            lm_studio_api_model,
            lm_studio_max_tokens,
            lm_studio_temperature,
            resolve_lm_studio_base,
        )

        return (
            resolve_lm_studio_base(),
            lm_studio_api_model(),
            lm_studio_temperature(),
            lm_studio_max_tokens(),
        )
    except Exception:
        return "http://127.0.0.1:1234/v1", "qwen2.5-1.5b", 0.3, 512


_ASTER_BASE, _ASTER_MODEL, _ASTER_TEMP, _ASTER_MAX_TOKENS = _defaults_from_aster()

DEFAULT_BASE = os.environ.get("LM_STUDIO_BASE_URL", _ASTER_BASE).rstrip("/")
DEFAULT_MODEL = os.environ.get("LM_STUDIO_MODEL", _ASTER_MODEL)
DEFAULT_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", str(_ASTER_TEMP)))
DEFAULT_MAX_TOKENS = int(os.environ.get("LLM_NUM_PREDICT", str(_ASTER_MAX_TOKENS)))


def _auth_headers() -> Dict[str, str]:
    """LM Studio local server auth — env override or ~/.lmstudio/.internal/lms-key-2."""
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    key = ""
    try:
        import sys
        from pathlib import Path

        eni_echo = (
            Path(__file__).resolve().parents[1]
            / "echo_nodes_interface"
            / "incoming"
            / "echo_nodes"
        )
        if eni_echo.is_dir() and str(eni_echo) not in sys.path:
            sys.path.insert(0, str(eni_echo))
        from lm_studio_auth import resolve_lmstudio_api_key

        key = resolve_lmstudio_api_key()
    except Exception:
        key = (
            os.environ.get("LM_API_TOKEN")
            or os.environ.get("LM_STUDIO_API_KEY")
            or os.environ.get("LMSTUDIO_API_KEY")
            or ""
        ).strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def server_reachable(base_url: str | None = None, timeout: float = 5.0) -> bool:
    """True if LM Studio local server responds (200 or 401 = up)."""
    base = (base_url or DEFAULT_BASE).rstrip("/")
    try:
        r = requests.get(f"{base}/models", headers=_auth_headers(), timeout=timeout)
        return r.status_code in (200, 401)
    except Exception:
        return False


def list_models(base_url: str | None = None, timeout: float = 5.0) -> List[str]:
    base = (base_url or DEFAULT_BASE).rstrip("/")
    try:
        r = requests.get(f"{base}/models", headers=_auth_headers(), timeout=timeout)
        if r.status_code == 401 and not _auth_headers().get("Authorization"):
            return [DEFAULT_MODEL]
        r.raise_for_status()
        data = r.json().get("data") or []
        return [str(m.get("id", "")) for m in data if m.get("id")]
    except Exception as e:
        logger.warning("LM Studio models list failed: %s", e)
        return []


def model_available(model: str, base_url: str | None = None) -> bool:
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not server_reachable(base):
        return False
    models = list_models(base)
    if not models:
        return server_reachable(base)
    if model in models:
        return True
    ml = model.lower()
    for m in models:
        if ml in m.lower() or m.lower() in ml:
            return True
        if "1.5" in ml and "1.5" in m.lower() and "instruct" in ml and "instruct" in m.lower():
            return True
    return False


def chat_completion(
    messages: List[Dict[str, str]],
    *,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = 300.0,
) -> Dict[str, Any]:
    base = (base_url or DEFAULT_BASE).rstrip("/")
    model = model or DEFAULT_MODEL
    temperature = DEFAULT_TEMPERATURE if temperature is None else temperature
    max_tokens = DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "enable_thinking": False,
    }
    try:
        from .aster_config import lm_studio_max_reasoning_tokens
        rcap = lm_studio_max_reasoning_tokens()
        if rcap is not None:
            payload["max_reasoning_tokens"] = rcap
    except Exception:
        pass
    r = requests.post(
        f"{base}/chat/completions",
        json=payload,
        headers=_auth_headers(),
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    out = process_lm_studio_body(body, compile_mode=False)
    clean = out["clean_content"]
    if not clean:
        return {"error": out["gate"].get("reason") or "substrate gate blocked", "substrate_gate": out["gate"], "proof": out["proof"]}
    usage = body.get("usage") or {}
    finish = ((body.get("choices") or [{}])[0]).get("finish_reason")
    det = usage.get("completion_tokens_details") or {}
    reasoning = int(det.get("reasoning_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    return {
        "response": clean,
        "eval_count": usage.get("completion_tokens", 0),
        "total_duration_ns": 0,
        "lm_studio_model": model,
        "substrate_quarantine": out.get("quarantine"),
        "proof": out.get("proof"),
        "upstream_finish_reason": finish,
        "substrate_usage": {
            "finish_reason": finish,
            "truncated": finish == "length",
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": completion,
            "reasoning_tokens": reasoning,
            "content_tokens": max(0, completion - reasoning),
        },
    }


async def stream_chat(
    messages: List[Dict[str, Any]],
    *,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = 300.0,
) -> AsyncIterator[str]:
    """Streaming disabled for LM Studio until stream sanitizer is wired; yield once."""
    out = chat_completion(
        messages,
        model=model,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    if text := out.get("response"):
        yield text
