"""
8788 telemetry stub — mic voice reports + synthetic aiFreq (original Garden logic).

Run: uvicorn repo.telemetry.stub:app --host 127.0.0.1 --port 8788
"""
from __future__ import annotations

import math
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Telemetry stub", version="0.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8787",
        "http://localhost:8787",
        "http://127.0.0.1:8788",
        "http://localhost:8788",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_VOICE_TTL_SEC = 2.5
_voice_freq = 0.0
_voice_amp = 0.0
_voice_at = 0.0


class VoiceReport(BaseModel):
    voiceFreq: float = Field(ge=0, le=20000)
    voiceAmp: float = Field(ge=0, le=1, default=0.0)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": "stub"}


@app.post("/api/voice")
async def voice(body: VoiceReport) -> dict[str, str]:
    global _voice_freq, _voice_amp, _voice_at
    _voice_freq = float(body.voiceFreq)
    _voice_amp = float(body.voiceAmp)
    _voice_at = time.time()
    return {"status": "ok", "source": "mic"}


@app.get("/api/telemetry")
async def telemetry() -> dict[str, float | str]:
    t = time.time()
    age = t - _voice_at
    use_mic = age <= _VOICE_TTL_SEC and _voice_freq > 30
    return {
        "t": t,
        "mode": "stub",
        "voiceSource": "mic" if use_mic else "synthetic",
        "voiceFreq": _voice_freq if use_mic else 200.0 + 80.0 * math.sin(t * 1.1),
        "aiFreq": 200.0 + 80.0 * math.cos(t * 0.9),
        "aiAmplitude": float(0.15 + 0.08 * (math.sin(t * 1.7) ** 2)),
        "latencyMs": float(18.0 + 6.0 * math.sin(t * 0.4)),
    }
