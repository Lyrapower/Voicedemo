"""Substrate-layer /health block for Entry B HUD (8787). No UI-side inference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .garden_gateway import GATEWAY_URL, gateway_health

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHALLENGE_LOG = _REPO_ROOT / "grid-sovereign-runtime" / ".grid_cleanroom" / "challenge_log.json"
_DEFAULT_KEYHOLDER_TTL = 90


def _keyholder_from_log(ttl: int = _DEFAULT_KEYHOLDER_TTL) -> dict[str, Any]:
    if not _CHALLENGE_LOG.exists():
        return {
            "challenge_ttl_seconds": ttl,
            "last_verified_at": None,
            "last_verdict": None,
            "line": "keyholder: no recent challenge",
        }
    try:
        log = json.loads(_CHALLENGE_LOG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "challenge_ttl_seconds": ttl,
            "last_verified_at": None,
            "last_verdict": None,
            "line": "keyholder: no recent challenge",
        }
    history = log.get("history") or []
    last_verified_at = None
    for entry in reversed(history):
        if entry.get("verdict") == "VERIFIED_KEYHOLDER":
            last_verified_at = entry.get("at")
            break
    if last_verified_at and isinstance(last_verified_at, str):
        try:
            from datetime import datetime, timezone

            at_raw = last_verified_at.replace("Z", "+00:00")
            at_ts = datetime.fromisoformat(at_raw).timestamp()
            age = datetime.now(timezone.utc).timestamp() - at_ts
            if 0 <= age <= ttl:
                return {
                    "challenge_ttl_seconds": ttl,
                    "last_verified_at": last_verified_at,
                    "last_verdict": "VERIFIED_KEYHOLDER",
                    "line": f"keyholder: VERIFIED_KEYHOLDER @ {last_verified_at}",
                }
        except (ValueError, TypeError, OSError):
            pass
    return {
        "challenge_ttl_seconds": ttl,
        "last_verified_at": None,
        "last_verdict": None,
        "line": "keyholder: no recent challenge",
    }


def build_substrate_health(
    *,
    compiler_ready: bool,
    substrates_available: int,
    substrates_total: int,
    compiler_role: str | None,
) -> dict[str, Any]:
    gw = gateway_health()
    gw_port = urlparse(GATEWAY_URL).port or 8501

    gateway = {
        "port": gw_port,
        "reachable": gw is not None,
        "status": gw.get("status") if isinstance(gw, dict) else None,
        "model": gw.get("model") if isinstance(gw, dict) else None,
    }

    if gw is not None and gw.get("status") == "ok":
        gateway_line = f"gateway {gw_port} ✓"
    elif gw is None:
        gateway_line = f"gateway {gw_port} unreachable"
    else:
        gateway_line = f"gateway {gw_port} status={gw.get('status')}"

    model = gateway.get("model")
    model_line = f"{model} loaded" if model else "model unavailable"

    if compiler_ready:
        compiler_line = "compiler ready"
    else:
        compiler_line = f"compiler not ready ({substrates_available}/{substrates_total})"

    keyholder = None
    if isinstance(gw, dict) and isinstance(gw.get("keyholder"), dict):
        keyholder = gw["keyholder"]
    if keyholder is None:
        keyholder = _keyholder_from_log()

    hud_lines = [
        gateway_line,
        model_line,
        compiler_line,
        keyholder.get("line", "keyholder: no recent challenge"),
    ]

    return {
        "gateway": gateway,
        "compiler": {
            "ready": compiler_ready,
            "substrates_available": substrates_available,
            "substrates_total": substrates_total,
            "role": compiler_role,
        },
        "keyholder": keyholder,
        "hud_lines": hud_lines,
    }
