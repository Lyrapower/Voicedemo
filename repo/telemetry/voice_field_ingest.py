"""voice-field-link v1 — 8787 /ingest remote mic + §2.1 合流归一.

不变量:127.0.0.1 only;坏帧丢弃计数;帧停 >2s 源 idle;无反向写入语音链.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

IDLE_SEC = 2.0
PEAK_WINDOW_SEC = 30.0
PEAK_FLOOR = 0.05

_REQUIRED = frozenset({"ts", "src", "energy", "voice_hz", "vad", "tts", "barge"})


@dataclass
class _SourceTrack:
    src: str
    peaks: deque[tuple[float, float]] = field(default_factory=deque)
    last_ts: float = 0.0
    energy_raw: float = 0.0
    voice_hz: float | None = None
    vad: str = "silence"
    tts: bool = False
    barge: bool = False
    bad_frames: int = 0

    def _trim_peaks(self, now: float) -> None:
        cutoff = now - PEAK_WINDOW_SEC
        while self.peaks and self.peaks[0][0] < cutoff:
            self.peaks.popleft()

    def _peak(self) -> float:
        if not self.peaks:
            return PEAK_FLOOR
        return max(PEAK_FLOOR, max(e for _, e in self.peaks))

    def ingest(self, frame: dict) -> bool:
        now = time.time()
        try:
            ts = float(frame["ts"])
            energy = float(frame["energy"])
            voice_hz = frame.get("voice_hz")
            if voice_hz is not None:
                voice_hz = float(voice_hz)
            vad = str(frame["vad"])
            tts = bool(frame["tts"])
            barge = bool(frame["barge"])
        except (TypeError, ValueError, KeyError):
            self.bad_frames += 1
            return False
        if vad not in ("speech", "silence"):
            self.bad_frames += 1
            return False
        self.last_ts = now if ts <= 0 else ts
        self.energy_raw = max(0.0, min(1.0, energy))
        self.peaks.append((now, self.energy_raw))
        self._trim_peaks(now)
        self.voice_hz = voice_hz if voice_hz and voice_hz > 0 else None
        self.vad = vad
        self.tts = tts
        self.barge = barge
        return True

    def normalized_energy(self) -> float:
        return min(1.0, self.energy_raw / self._peak())

    def active(self, now: float | None = None) -> bool:
        t = now if now is not None else time.time()
        return (t - self.last_ts) < IDLE_SEC and self.vad == "speech"

    def snapshot(self) -> dict:
        now = time.time()
        active = self.active(now)
        return {
            "src": self.src,
            "energy_norm": round(self.normalized_energy(), 4) if active or self.last_ts > 0 else 0.0,
            "voice_hz": self.voice_hz,
            "vad": self.vad if active else "silence",
            "tts": self.tts if active else False,
            "barge": self.barge,
            "active": active,
            "last_ts": self.last_ts,
        }


class FieldIngestHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sources: dict[str, _SourceTrack] = {}
        self._last_barge_ts = 0.0

    def ingest_frame(self, frame: dict) -> bool:
        src = str(frame.get("src") or "phone")
        with self._lock:
            track = self._sources.get(src)
            if track is None:
                track = _SourceTrack(src=src)
                self._sources[src] = track
            ok = track.ingest(frame)
            if ok and frame.get("barge"):
                self._last_barge_ts = time.time()
            return ok

    def field_link_snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            sources = {k: t.snapshot() for k, t in self._sources.items()}
            bad = sum(t.bad_frames for t in self._sources.values())
        phone = sources.get("phone") or {
            "src": "phone",
            "energy_norm": 0.0,
            "voice_hz": None,
            "vad": "silence",
            "tts": False,
            "barge": False,
            "active": False,
            "last_ts": 0.0,
        }
        mic_label = "idle"
        if phone.get("active"):
            mic_label = "listening(phone)"
        tts_out = bool(phone.get("active") and phone.get("tts"))
        barge_pulse = (now - self._last_barge_ts) < 0.35
        return {
            "phone": phone,
            "mic_label": mic_label,
            "tts_out": tts_out,
            "barge_pulse": barge_pulse,
            "bad_frames": bad,
        }


HUB = FieldIngestHub()


def build_ingest_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/ingest")
    async def ingest_ws(ws: WebSocket) -> None:
        host = (ws.client.host if ws.client else "") or ""
        if host not in ("127.0.0.1", "::1", "localhost"):
            await ws.close(code=1008, reason="localhost only")
            return
        await ws.accept()
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if not _REQUIRED.issubset(obj.keys()):
                    with HUB._lock:
                        HUB._sources.setdefault("phone", _SourceTrack(src="phone")).bad_frames += 1
                    continue
                HUB.ingest_frame(obj)
        except WebSocketDisconnect:
            pass

    return router


def field_link_for_telemetry() -> dict:
    return HUB.field_link_snapshot()
