"""
FastAPI telemetry stub for Garden / sound-lab.

Run from repo root (see scripts/start_telemetry.sh):
  uvicorn telemetry.main:app --host 127.0.0.1 --port 8788
"""
from __future__ import annotations

import math
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Telemetry stub", version="0.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/telemetry")
async def telemetry() -> dict[str, float]:
    t = time.time()
    return {
        "t": t,
        "voiceFreq": 200.0 + 80.0 * math.sin(t * 1.1),
        "aiFreq": 200.0 + 80.0 * math.cos(t * 0.9),
        "aiAmplitude": float(0.15 + 0.08 * (math.sin(t * 1.7) ** 2)),
        "latencyMs": float(18.0 + 6.0 * math.sin(t * 0.4)),
    }
