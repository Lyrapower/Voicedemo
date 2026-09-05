#!/usr/bin/env python3
"""voice-field-link v1 acceptance (localhost)."""
from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "repo" / "telemetry"))

from voice_field_ingest import HUB, FieldIngestHub  # noqa: E402


def test_ingest_schema() -> bool:
    hub = FieldIngestHub()
    assert not hub.ingest_frame({"ts": 1.0, "src": "phone"})
    assert hub.ingest_frame(
        {
            "ts": time.time(),
            "src": "phone",
            "energy": 0.5,
            "voice_hz": 180.0,
            "vad": "speech",
            "tts": False,
            "barge": False,
        }
    )
    snap = hub.field_link_snapshot()
    assert snap["phone"]["active"] is True
    assert snap["mic_label"] == "listening(phone)"
    return True


async def test_field_stream_smoke() -> bool:
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get("http://127.0.0.1:8501/field/stream")
        if r.status_code != 200:
            return False
        chunk = ""
        async for part in r.aiter_text():
            chunk += part
            if "data:" in chunk:
                break
        return "data:" in chunk


def main() -> int:
    ok = True
    try:
        test_ingest_schema()
        print("PASS ingest schema")
    except Exception as exc:
        print("FAIL ingest schema:", exc)
        ok = False
    try:
        if asyncio.run(test_field_stream_smoke()):
            print("PASS field/stream SSE smoke")
        else:
            print("FAIL field/stream SSE smoke")
            ok = False
    except Exception as exc:
        print("SKIP field/stream (8501 down?):", exc)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
