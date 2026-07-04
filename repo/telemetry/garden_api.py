from __future__ import annotations

import sys
from pathlib import Path

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .garden_gateway import gateway_health, gateway_reachable
from .live_tts import report_voice, set_presence, speak_now, telemetry_payload

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.garden_services import (  # noqa: E402
    compiled_memory_payload,
    music_catalog,
    resolve_music_file,
    run_memory_compile,
)

router = APIRouter(tags=["garden"])


class VoiceReport(BaseModel):
    voiceFreq: float = Field(ge=0, le=20000)
    voiceAmp: float = Field(ge=0, le=1, default=0.0)


class SpeakRequest(BaseModel):
    text: str | None = None


class PresenceRequest(BaseModel):
    enabled: bool


class DialogueRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


@router.get("/api/gateway/health")
async def gateway_status() -> dict:
    health = gateway_health()
    return {
        "reachable": gateway_reachable(),
        "health": health or {},
    }


@router.post("/api/dialogue")
async def dialogue(body: DialogueRequest) -> dict:
    """Garden → sovereign gateway (9B) → TTS."""
    return speak_now(body.prompt)


@router.get("/api/telemetry")
async def telemetry() -> dict[str, float | str | bool]:
    return telemetry_payload()


_WS_PUSH_HZ = 20  # matches the frontend mock's 50ms cadence


@router.websocket("/live")
async def live_ws(ws: WebSocket) -> None:
    """Push live telemetry as {t, aiFreq, aiAmplitude, ...} frames.

    The Vite garden SocketClient connects to ws://host:8787/live; until now
    this endpoint did not exist, so the field always ran on mock data.
    """
    await ws.accept()
    interval = 1.0 / _WS_PUSH_HZ
    try:
        while True:
            payload = telemetry_payload()
            await ws.send_json(payload)
            await asyncio.sleep(interval)
    except (WebSocketDisconnect, RuntimeError):
        return


@router.post("/api/voice")
async def voice(body: VoiceReport) -> dict[str, str]:
    report_voice(body.voiceFreq, body.voiceAmp)
    return {"status": "ok", "source": "mic"}


@router.post("/api/presence")
async def presence(body: PresenceRequest) -> dict[str, bool]:
    return set_presence(body.enabled)


@router.post("/api/speak")
async def speak(body: SpeakRequest | None = None) -> dict[str, str]:
    text = body.text if body else None
    return speak_now(text)


@router.get("/api/memory/compiled")
async def memory_compiled() -> dict:
    """Entry B (8787): Grid compile — sovereign on particle router, not proxied to 8500."""
    return compiled_memory_payload()


@router.post("/api/memory/compile")
async def memory_compile() -> dict:
    return run_memory_compile()


@router.get("/api/music/catalog")
async def music_list() -> dict:
    return music_catalog()


@router.get("/assets/music/{filename}")
async def music_asset(filename: str) -> FileResponse:
    path = resolve_music_file(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="track not found")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})
