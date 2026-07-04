"""Resolve LM Studio API key from env only (LM_API_TOKEN is official name)."""

from __future__ import annotations

import os


def resolve_lmstudio_api_key() -> str:
    for name in ("LM_API_TOKEN", "LM_STUDIO_API_KEY", "LMSTUDIO_API_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def lm_auth_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = resolve_lmstudio_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers
