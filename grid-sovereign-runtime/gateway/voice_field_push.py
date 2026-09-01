"""voice-field-link v1 — 8504→8787 feature frames (旁路;语音主链零阻塞).

不变量:单向特征(energy/hz/vad/tts/barge);无波形/文本;8787 不在则丢帧+30s重连;
§1.1 回调只入队;§1.2 barge 只转发主链打断事件,禁止推断.
"""
from __future__ import annotations

import json
import logging
import math
import queue
import struct
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger("voice_field_push")

INGEST_URL = "ws://127.0.0.1:8787/ingest"
FRAME_INTERVAL = 0.05  # 20Hz
PCM_QUEUE_MAX = 8
RECONNECT_SEC = 30.0
SAMPLE_RATE = 16000
VAD_RMS = 0.015


@dataclass
class _FeatureFrame:
    ts: float
    src: str
    energy: float
    voice_hz: float | None
    vad: str
    tts: bool
    barge: bool


class VoiceFieldPusher:
    """8504 旁路:有界 PCM 队列 + worker + 出口槽深度 1 WS 发送."""

    def __init__(self, ingest_url: str = INGEST_URL) -> None:
        self._ingest_url = ingest_url
        self._pcm_q: queue.Queue[bytes] = queue.Queue(maxsize=PCM_QUEUE_MAX)
        self._slot: _FeatureFrame | None = None
        self._slot_lock = threading.Lock()
        self._session_active = False
        self._src = "phone"
        self._tts = False
        self._barge_once = False
        self._barge_lock = threading.Lock()
        self._pcm_buf = bytearray()
        self._ws_connected = False
        self._last_connect_attempt = 0.0
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, name="voice-field-worker", daemon=True)
        self._sender = threading.Thread(target=self._sender_loop, name="voice-field-sender", daemon=True)
        self._worker.start()
        self._sender.start()

    def start_session(self, src: str = "phone") -> None:
        self._src = src or "phone"
        self._session_active = True
        self._pcm_buf.clear()
        with self._barge_lock:
            self._barge_once = False
        self._tts = False

    def end_session(self) -> None:
        self._session_active = False
        self._pcm_buf.clear()
        with self._slot_lock:
            self._slot = None
        while not self._pcm_q.empty():
            try:
                self._pcm_q.get_nowait()
            except queue.Empty:
                break

    def enqueue_pcm(self, pcm: bytes) -> None:
        if not self._session_active or not pcm:
            return
        try:
            self._pcm_q.put_nowait(pcm)
        except queue.Full:
            try:
                self._pcm_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._pcm_q.put_nowait(pcm)
            except queue.Full:
                pass

    def set_tts(self, active: bool) -> None:
        self._tts = bool(active)

    def mark_barge(self) -> None:
        """§1.2 — 仅转发语音主链 interrupt.ack / barge_in 事件."""
        with self._barge_lock:
            self._barge_once = True

    def _drain_pcm(self) -> None:
        while True:
            try:
                chunk = self._pcm_q.get_nowait()
            except queue.Empty:
                break
            self._pcm_buf.extend(chunk)
            if len(self._pcm_buf) > SAMPLE_RATE * 2 * 4:
                del self._pcm_buf[: SAMPLE_RATE * 2]

    @staticmethod
    def _rms_and_f0(pcm16: bytes) -> tuple[float, float | None]:
        n = len(pcm16) // 2
        if n < 128:
            return 0.0, None
        samples = struct.unpack(f"<{n}h", pcm16[: n * 2])
        acc = sum(s * s for s in samples)
        rms = math.sqrt(acc / n) / 32768.0
        if rms < VAD_RMS:
            return rms, None
        min_lag = SAMPLE_RATE // 400
        max_lag = min(SAMPLE_RATE // 80, n // 2 - 1)
        best_lag = 0
        best_corr = 0.0
        for lag in range(min_lag, max_lag + 1):
            corr = sum(samples[i] * samples[i + lag] for i in range(n - lag))
            if corr > best_corr:
                best_corr = corr
                best_lag = lag
        if best_lag <= 0 or best_corr <= 0:
            return rms, None
        return rms, SAMPLE_RATE / best_lag

    def _worker_loop(self) -> None:
        next_tick = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now < next_tick:
                time.sleep(min(0.01, next_tick - now))
                continue
            next_tick += FRAME_INTERVAL
            if not self._session_active:
                continue
            self._drain_pcm()
            need = int(SAMPLE_RATE * FRAME_INTERVAL) * 2
            if len(self._pcm_buf) < need:
                continue
            chunk = bytes(self._pcm_buf[:need])
            del self._pcm_buf[:need]
            rms, f0 = self._rms_and_f0(chunk)
            barge = False
            with self._barge_lock:
                if self._barge_once:
                    barge = True
                    self._barge_once = False
            frame = _FeatureFrame(
                ts=time.time(),
                src=self._src,
                energy=min(1.0, rms * 4.0),
                voice_hz=round(f0, 1) if f0 else None,
                vad="speech" if rms >= VAD_RMS else "silence",
                tts=self._tts,
                barge=barge,
            )
            with self._slot_lock:
                self._slot = frame

    def _sender_loop(self) -> None:
        ws = None
        while not self._stop.is_set():
            if not self._session_active:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass
                    ws = None
                    if self._ws_connected:
                        logger.info("voice-field-push disconnected (session end)")
                    self._ws_connected = False
                time.sleep(0.05)
                continue

            frame: _FeatureFrame | None
            with self._slot_lock:
                frame = self._slot
                self._slot = None
            if frame is None:
                time.sleep(FRAME_INTERVAL)
                continue

            if ws is None:
                now = time.monotonic()
                if now - self._last_connect_attempt < RECONNECT_SEC:
                    time.sleep(0.05)
                    continue
                self._last_connect_attempt = now
                try:
                    import websockets.sync.client as wsc

                    ws = wsc.connect(self._ingest_url, open_timeout=2)
                    if not self._ws_connected:
                        logger.info("voice-field-push connected %s", self._ingest_url)
                    self._ws_connected = True
                except Exception:
                    self._ws_connected = False
                    ws = None
                    time.sleep(0.05)
                    continue

            try:
                ws.send(json.dumps({
                    "ts": frame.ts,
                    "src": frame.src,
                    "energy": round(frame.energy, 4),
                    "voice_hz": frame.voice_hz,
                    "vad": frame.vad,
                    "tts": frame.tts,
                    "barge": frame.barge,
                }))
            except Exception:
                if self._ws_connected:
                    logger.info("voice-field-push disconnected from %s", self._ingest_url)
                self._ws_connected = False
                try:
                    ws.close()
                except Exception:
                    pass
                ws = None
                self._last_connect_attempt = time.monotonic()

            time.sleep(FRAME_INTERVAL)


_pusher: VoiceFieldPusher | None = None
_pusher_lock = threading.Lock()


def get_field_pusher() -> VoiceFieldPusher:
    global _pusher
    with _pusher_lock:
        if _pusher is None:
            _pusher = VoiceFieldPusher()
        return _pusher
