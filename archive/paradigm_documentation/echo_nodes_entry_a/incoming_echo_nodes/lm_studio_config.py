"""Entry A — LM Studio connection (shared by /stream, /echo-node, SynCon)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lm_studio_auth import resolve_lmstudio_api_key

ANCHOR_PATH = Path(__file__).resolve().parent / "syncon/config/anchor.json"


def lm_settings() -> dict[str, Any]:
    with open(ANCHOR_PATH, encoding="utf-8") as f:
        anchor = json.load(f)
    lm = anchor.get("lm_studio", {})
    return {
        "base_url": str(lm.get("base_url", "http://127.0.0.1:1234/v1")),
        "model": str(lm.get("model", "mlx-community/Qwen2.5-1.5B-4bit")),
        "timeout_s": float(lm.get("timeout_s", 300)),
        "api_key_set": bool(resolve_lmstudio_api_key()),
    }
