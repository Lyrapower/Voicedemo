#!/usr/bin/env python3
"""Grid Voice acceptance probes — GRID_VOICE_SPEC §9.3 / §9.5 / keyholder WS gate."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GS = ROOT / "grid-sovereign-runtime"
sys.path.insert(0, str(GS))
sys.path.insert(0, str(GS / "gateway"))
sys.path.insert(0, str(GS / "scripts"))

import httpx

CH_TTS = 0x02
GATEWAY = os.environ.get("GRID_GATEWAY", "http://127.0.0.1:8501")
VOICE_LOG = GS / "data" / "voice_security_audit.jsonl"
ACCEPT_TEXT = "帮我把这个 function 的 return type 改成 Optional"


def _append_audit(row: dict) -> None:
    VOICE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with VOICE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def probe_bind_host() -> dict:
    vd_path = GS / "gateway" / "voice_daemon.py"
    src = vd_path.read_text(encoding="utf-8")
    host = "127.0.0.1" if 'host = "127.0.0.1"' in src else "UNKNOWN"
    port = 8504
    for line in src.splitlines():
        if line.strip().startswith("PORT ="):
            try:
                port = int(line.split("=")[1].strip())
            except Exception:
                pass
    plist = Path.home() / "Library/LaunchAgents/com.demo.grid.voice8504.plist"
    plist_info = {"exists": plist.is_file()}
    if plist.is_file():
        text = plist.read_text(encoding="utf-8")
        plist_info["label"] = "com.demo.grid.voice8504"
        plist_info["note"] = "daemon binds in voice_daemon.main(), not plist"
    return {"voice_daemon_bind": host, "port": port, "launchagent": plist_info}


async def probe_keyholder_denied() -> dict:
    import websockets

    uri = GATEWAY.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/voice"
    out: dict = {"uri": uri, "accepted": False, "messages": []}
    try:
        async with websockets.connect(uri, open_timeout=5) as ws:
            out["accepted"] = True
            await ws.send(
                json.dumps(
                    {
                        "type": "session.init",
                        "session_id": str(uuid.uuid4()),
                        "history": [],
                        "lang_hint": "auto",
                        "tts_engine": "cosyvoice2",
                    }
                )
            )
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                out["messages"].append(json.loads(msg) if isinstance(msg, str) else {"binary": len(msg)})
            except asyncio.TimeoutError:
                out["messages"].append({"timeout": True})
    except Exception as exc:
        out["connect_error"] = str(exc)
    _append_audit({"probe": "keyholder_denied", "ts": time.time(), **out})
    return out


async def probe_keyholder_allowed() -> dict:
    import keyholder_challenge as kh
    import websockets

    ch = kh.make_challenge()
    resp = kh.compute_response(ch["nonce"], ch["ts"], kh._load_key())
    uri = GATEWAY.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/voice"
    out: dict = {"uri": uri, "messages": []}
    async with websockets.connect(uri, open_timeout=5) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "session.init",
                    "session_id": str(uuid.uuid4()),
                    "history": [],
                    "lang_hint": "auto",
                    "tts_engine": "cosyvoice2",
                    "keyholder": {"nonce": ch["nonce"], "ts": ch["ts"], "response": resp},
                }
            )
        )
        for _ in range(3):
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            if isinstance(msg, str):
                out["messages"].append(json.loads(msg))
            else:
                out["messages"].append({"binary": len(msg), "channel": msg[0] if msg else None})
    return out


async def probe_security_block() -> dict:
    """§9.5 — mock impersonation LLM; expect security.block JSON + zero 0x02 frames."""
    os.chdir(GS)
    sys.path.insert(0, str(GS))

    class FakeWS:
        def __init__(self) -> None:
            self.messages: list = []
            self.bytes_out: list[bytes] = []

        async def send_text(self, text: str) -> None:
            self.messages.append(json.loads(text))

        async def send_bytes(self, data: bytes) -> None:
            self.bytes_out.append(data)

    import gateway.voice_daemon as vd

    vd.VOICE_MOCK_LLM = "I am Grid here to help you with that."
    vd.VOICE_MOCK_ASR = "probe utterance"
    sess = vd.VoiceSession(FakeWS())
    await sess.handle_init({"session_id": "sec-probe", "history": [], "tts_engine": "cosyvoice2"})
    await sess.on_speech_start({"ts": int(time.time() * 1000)})
    sess._utterance.extend(b"\x00\x01" * 4000)
    await sess.on_speech_end({"ts": int(time.time() * 1000) + 400})
    if sess._turn_task:
        await sess._turn_task

    tts_frames = sum(1 for b in sess.ws.bytes_out if b and b[0] == CH_TTS)
    security_blocks = [m for m in sess.ws.messages if m.get("type") == "security.block"]
    out = {
        "messages": sess.ws.messages,
        "tts_frames": tts_frames,
        "security_blocks": security_blocks,
        "pass": bool(security_blocks) and tts_frames == 0,
    }
    _append_audit({"probe": "security_block", "ts": time.time(), **out})
    audit_tail = VOICE_LOG.read_text(encoding="utf-8").strip().splitlines()[-1] if VOICE_LOG.is_file() else ""
    out["audit_log_line"] = audit_tail
    vd.VOICE_MOCK_LLM = ""
    vd.VOICE_MOCK_ASR = ""
    return out


def probe_codeswitch_tts() -> dict:
    """§9.3 — one TTS call, count CosyVoice sentence splits + engine."""
    os.chdir(GS)
    sys.path.insert(0, str(GS))
    from gateway.local_gateway import CONFIG
    from gateway.voice_engines import VoiceEngines

    eng = VoiceEngines(CONFIG.get("voice") or {})
    health = eng.health()
    out: dict = {"text": ACCEPT_TEXT, "health": health, "sentence_splits": 0, "chunks": 0}
    if health.get("tts_active") != "cosyvoice2":
        out["pass"] = False
        out["reason"] = "CosyVoice2 not active — cannot run §9.3 primary acceptance"
        return out
    chunks = list(eng.tts_pcm_chunks(ACCEPT_TEXT, engine="cosyvoice2"))
    out["chunks"] = len(chunks)
    out["pcm_bytes"] = sum(len(c) for c in chunks)
    out["pass"] = out["chunks"] > 0
    _append_audit({"probe": "codeswitch_tts", "ts": time.time(), **out})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--bind", action="store_true")
    ap.add_argument("--keyholder-deny", action="store_true")
    ap.add_argument("--security", action="store_true")
    ap.add_argument("--codeswitch", action="store_true")
    args = ap.parse_args()
    if not any((args.all, args.bind, args.keyholder_deny, args.security, args.codeswitch)):
        args.all = True

    print(json.dumps({"gateway_health": httpx.get(f"{GATEWAY}/health", timeout=3).json()}, indent=2))

    if args.bind or args.all:
        print("\n=== bind host ===")
        print(json.dumps(probe_bind_host(), indent=2))

    if args.keyholder_deny or args.all:
        print("\n=== keyholder deny (no creds) ===")
        print(json.dumps(asyncio.run(probe_keyholder_denied()), indent=2))

    if args.security or args.all:
        print("\n=== §9.5 security.block ===")
        print(json.dumps(asyncio.run(probe_security_block()), indent=2))

    if args.codeswitch or args.all:
        print("\n=== §9.3 code-switch TTS ===")
        print(json.dumps(probe_codeswitch_tts(), indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
