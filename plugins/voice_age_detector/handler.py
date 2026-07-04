"""Voice age detector plugin — active deployment entry point."""

from __future__ import annotations

from typing import Any


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a minimal detection result; wire real logic when spec is ready."""
    audio_ref = payload.get("audio_ref") or payload.get("path")
    return {
        "plugin": "voice_age_detector",
        "status": "ok",
        "audio_ref": audio_ref,
        "age_band": None,
        "confidence": None,
    }
