"""Audio8 ONNX TTS health probe — distinct from harness :8630."""
from __future__ import annotations

import httpx

from .config import Audio8VoiceConfig
from .port_util import port_bindable


async def probe_audio8(cfg: Audio8VoiceConfig) -> dict:
    """Health slice for harness /health — never conflate with harness port."""
    base = {
        "service": "audio8-tts-onnx",
        "host": cfg.host,
        "port": cfg.port,
        "enabled": cfg.enabled,
        "model": cfg.model,
    }
    if not cfg.enabled:
        base["status"] = "disabled"
        base["reachable"] = False
        base["port_free"] = port_bindable(cfg.host, cfg.port)
        return base

    url = f"http://{cfg.host}:{cfg.port}/api/health"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith(
                "application/json"
            ):
                body = r.json()
                if body.get("ok") is True:
                    return {
                        **base,
                        "status": "up",
                        "reachable": True,
                        "port_free": False,
                        "detail": body,
                    }
            return {
                **base,
                "status": "unexpected_response",
                "reachable": False,
                "port_free": port_bindable(cfg.host, cfg.port),
                "http_status": r.status_code,
            }
    except httpx.HTTPError as exc:
        free = port_bindable(cfg.host, cfg.port)
        return {
            **base,
            "status": "down" if not free else "not_running",
            "reachable": False,
            "port_free": free,
            "error": type(exc).__name__,
        }
