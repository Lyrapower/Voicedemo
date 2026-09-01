"""voice-field-link v1 — 8501 GET /field/stream SSE (只读).

§3.1:8501 主动 ws 订阅 8787 /live;8787 零推送改动(除 /ingest).
不变量:单向回显;15s keepalive;断连客户端显示 idle.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

logger = logging.getLogger("field_stream")

GARDEN_LIVE_WS = "ws://127.0.0.1:8787/live"
PUSH_HZ = 3.0
KEEPALIVE_SEC = 15.0

_cache: dict[str, Any] = {
    "ts": 0.0,
    "online": False,
    "anchor_coherence": None,
    "anchor_state": "idle",
    "zone": None,
    "breath_sync": None,
    "mic_label": "idle",
}
_cache_lock = asyncio.Lock()
_subscriber_task: asyncio.Task | None = None


def _field_event_payload(raw: dict) -> dict:
    fl = raw.get("field_link") or {}
    return {
        "ts": time.time(),
        "online": True,
        "garden": "live" if raw.get("active") or fl.get("phone", {}).get("active") else "idle",
        "anchor_coherence": raw.get("anchor_coherence"),
        "anchor_state": raw.get("anchor_state", "idle"),
        "zone": raw.get("zone"),
        "breath_sync": raw.get("breath_sync"),
        "mic_label": fl.get("mic_label", "idle"),
        "tts_out": fl.get("tts_out", False),
        "barge_pulse": fl.get("barge_pulse", False),
    }


async def _garden_subscriber_loop() -> None:
    global _cache
    while True:
        try:
            import websockets

            async with websockets.connect(GARDEN_LIVE_WS, open_timeout=3) as ws:
                logger.info("field-stream subscribed %s", GARDEN_LIVE_WS)
                async for message in ws:
                    if not isinstance(message, str):
                        continue
                    try:
                        raw = json.loads(message)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(raw, dict):
                        continue
                    snap = _field_event_payload(raw)
                    async with _cache_lock:
                        _cache = snap
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("field-stream garden ws: %s", exc)
            async with _cache_lock:
                _cache = {
                    "ts": time.time(),
                    "online": False,
                    "garden": "idle",
                    "anchor_coherence": None,
                    "anchor_state": "idle",
                    "zone": None,
                    "breath_sync": None,
                    "mic_label": "idle",
                }
            await asyncio.sleep(5.0)


def _ensure_subscriber() -> None:
    global _subscriber_task
    if _subscriber_task is None or _subscriber_task.done():
        _subscriber_task = asyncio.create_task(_garden_subscriber_loop())


def build_field_stream_router() -> APIRouter:
    router = APIRouter()

    @router.get("/field/stream")
    async def field_stream() -> StreamingResponse:
        _ensure_subscriber()

        async def gen():
            last_push = 0.0
            last_keep = time.monotonic()
            interval = 1.0 / PUSH_HZ
            while True:
                now = time.monotonic()
                if now - last_push >= interval:
                    async with _cache_lock:
                        payload = dict(_cache)
                    payload["ts"] = time.time()
                    if not payload.get("online"):
                        payload["garden"] = "idle"
                        payload["anchor_state"] = "idle"
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    last_push = now
                if now - last_keep >= KEEPALIVE_SEC:
                    yield ": keepalive\n\n"
                    last_keep = now
                await asyncio.sleep(0.05)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
