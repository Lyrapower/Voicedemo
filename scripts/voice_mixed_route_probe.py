#!/usr/bin/env python3
"""守秤验收: 混切句 → CosyVoice2 + MPS device + RTF + WS tts.sentence.start."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "grid-sovereign-runtime"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gateway"))
os.chdir(ROOT)

MIXED = "帮我把这个 function 的 return type 改成 Optional"
PURE_EN = "Hello world, this is a routing probe."


def locale_probe() -> None:
    from gateway.voice_engines import classify_tts_locale, is_pure_english_sentence

    print("=== locale classify ===")
    for text in (MIXED, PURE_EN):
        print(
            json.dumps(
                {
                    "text": text,
                    "locale": classify_tts_locale(text),
                    "pure_en": is_pure_english_sentence(text),
                },
                ensure_ascii=False,
            )
        )


def engine_probe() -> dict:
    from gateway.local_gateway import CONFIG
    from gateway.voice_engines import VoiceEngines

    print("\n=== engine synthesis (bootstrap) ===")
    eng = VoiceEngines(CONFIG.get("voice") or {})
    eng.bootstrap()
    chosen, route = eng.resolve_tts_engine(MIXED, engine="auto")
    print("resolve:", chosen, route.reason)
    if chosen != "cosyvoice2":
        raise SystemExit(f"FAIL: expected cosyvoice2, got {chosen}")

    for chunk in eng.tts_pcm_chunks(MIXED, engine="auto"):
        _ = chunk
    stats = eng.last_tts_synthesis or {}
    print("metrics:", json.dumps(stats, ensure_ascii=False, indent=2))
    if not str(stats.get("device", "")).startswith("mps"):
        raise SystemExit(f"FAIL: device not mps: {stats.get('device')}")
    if stats.get("rtf") is None:
        raise SystemExit("FAIL: missing RTF")
    return stats


async def ws_probe() -> dict:
    import websockets

    print("\n=== WS turn (8504 direct, VOICE_MOCK_*) ===")
    uri = "ws://127.0.0.1:8504/ws/voice"
    sid = str(uuid.uuid4())
    tts_start = None
    tts_end = None

    async with websockets.connect(uri, open_timeout=10) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "session.init",
                    "session_id": sid,
                    "history": [],
                    "lang_hint": "auto",
                    "tts_engine": "auto",
                }
            )
        )
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            t = msg.get("type")
            if t == "session.ready":
                await ws.send(json.dumps({"type": "speech.start", "ts": int(time.time() * 1000)}))
                pcm = b"\x00\x01" * 8000
                frame = bytes([0x01]) + pcm
                await ws.send(frame)
                await ws.send(json.dumps({"type": "speech.end", "ts": int(time.time() * 1000)}))
            elif t == "tts.sentence.start":
                tts_start = msg
                print("tts.sentence.start:", json.dumps(msg, ensure_ascii=False))
            elif t == "tts.sentence.end":
                tts_end = msg
                print("tts.sentence.end:", json.dumps(msg, ensure_ascii=False))
                break
            elif t == "error":
                raise SystemExit(f"WS error: {msg}")

    if not tts_start or tts_start.get("engine") != "cosyvoice2":
        raise SystemExit(f"FAIL: WS engine not cosyvoice2: {tts_start}")
    if tts_start.get("locale") not in ("mixed", "zh"):
        raise SystemExit(f"FAIL: WS locale: {tts_start.get('locale')}")
    return {"start": tts_start, "end": tts_end}


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--ws-only", action="store_true")
    ap.add_argument("--engine-only", action="store_true")
    args = ap.parse_args()

    locale_probe()
    stats = None
    ws = None
    if not args.ws_only:
        stats = engine_probe()
    if not args.engine_only:
        try:
            ws = asyncio.run(ws_probe())
        except Exception as exc:
            print("WS probe failed:", exc)
            raise
    print("\n=== PASS summary ===")
    print(json.dumps({"engine_metrics": stats, "ws": ws}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
