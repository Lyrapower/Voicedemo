"""Garden v1 — macOS TTS + live telemetry (port 8790; 8787/8788 unchanged)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .garden_api import router as garden_router

app = FastAPI(title="Garden v1", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8790",
        "http://localhost:8790",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8787",
        "http://localhost:8787",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str | bool]:
    from .live_tts import tts_status

    return {"status": "ok", "port": "8790", **tts_status()}


app.include_router(garden_router)
