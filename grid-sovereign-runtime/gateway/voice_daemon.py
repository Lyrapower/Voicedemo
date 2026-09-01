"""Grid Voice daemon — :8504 WS pipeline per docs/GRID_VOICE_SPEC.md."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gateway.local_gateway import (  # noqa: E402
    CONFIG,
    _openai_chat_payload,
    _prepare_substrate_messages,
    cleanroom_gate_check,
    first_impersonation_hit,
)
from gateway.voice_engines import CH_MIC, VoiceEngines, classify_tts_locale, frame_tts  # noqa: E402
from gateway.voice_splitter import SentenceSplitter  # noqa: E402
from gateway.voice_field_push import get_field_pusher  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("voice_daemon")

VOICE_CFG = CONFIG.get("voice") or {}
PORT = int(VOICE_CFG.get("daemon_port") or 8504)
VOICE_MAX = int((VOICE_CFG.get("budgets") or {}).get("voice_max_tokens") or 400)
ABORT_BLOCKS = int((VOICE_CFG.get("security") or {}).get("abort_after_blocks") or 2)
SECURITY_AUDIT_LOG = ROOT / "data" / "voice_security_audit.jsonl"
VOICE_MOCK_LLM = os.environ.get("VOICE_MOCK_LLM", "").strip()
VOICE_MOCK_ASR = os.environ.get("VOICE_MOCK_ASR", "").strip()


@dataclass
class BootState:
    status: str = "initializing"  # initializing | ok | error
    progress: float = 0.0
    phase: str = "starting"
    detail: str = ""
    error: str | None = None
    asr_download: float | None = None


_boot = BootState()
_boot_lock = threading.Lock()
engines: VoiceEngines | None = None
_boot_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-bootstrap")


def _on_boot_progress(phase: str, progress: float, detail: str = "", **extra: Any) -> None:
    with _boot_lock:
        _boot.phase = phase
        _boot.progress = round(max(0.0, min(1.0, progress)), 3)
        if detail:
            _boot.detail = detail
        if "asr_download" in extra and extra["asr_download"] is not None:
            _boot.asr_download = round(float(extra["asr_download"]), 3)
    if detail:
        logger.info("voice boot [%s] %.0f%% — %s", phase, progress * 100, detail)


def _bootstrap_worker() -> None:
    global engines
    try:
        eng = VoiceEngines(VOICE_CFG)
        eng.bootstrap(_on_boot_progress)
        with _boot_lock:
            engines = eng
            _boot.status = "ok"
            _boot.progress = 1.0
            _boot.phase = "ready"
            _boot.detail = "engines ready"
        logger.info("voice engines ready asr=%s tts=%s", eng.health()["asr"], eng.health()["tts"])
    except Exception as exc:
        logger.exception("voice engine bootstrap failed")
        with _boot_lock:
            _boot.status = "error"
            _boot.error = str(exc)
            _boot.detail = str(exc)


def _require_engines() -> VoiceEngines:
    if engines is None or not engines.ready:
        raise RuntimeError("voice engines still initializing")
    return engines


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    loop = asyncio.get_running_loop()
    loop.run_in_executor(_boot_executor, _bootstrap_worker)
    yield


app = FastAPI(title="grid-voice-daemon", lifespan=_lifespan)


def _audit_security(event: dict) -> None:
    SECURITY_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), **event}
    with SECURITY_AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    logger.warning("voice security audit: %s", row)


class VState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass
class TurnLedger:
  spoken_sentences: list[str] = field(default_factory=list)
  pending_sentence: str | None = None
  security_blocks: int = 0
  llm_text: str = ""

  def spoken_text(self) -> str:
    parts = list(self.spoken_sentences)
    if self.pending_sentence:
      parts.append(self.pending_sentence)
    return "".join(parts)


class VoiceSession:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.state = VState.IDLE
        self.session_id = ""
        self.history: list[dict] = []
        self.lang_hint = "auto"
        self.tts_engine = "auto"
        self._utterance = bytearray()
        self._speech_start_ts = 0
        self._accept_audio = False
        self._turn_task: asyncio.Task | None = None
        self._abort = asyncio.Event()
        self._ledger = TurnLedger()
        self._tts_idx = 0
        self._interrupt_gate = False
        self._thinking_user_buf = ""

    async def send_json(self, obj: dict) -> None:
        await self.ws.send_text(json.dumps(obj, ensure_ascii=False))

    async def send_bytes(self, data: bytes) -> None:
        await self.ws.send_bytes(data)

    async def set_state(self, value: VState) -> None:
        self.state = value
        get_field_pusher().set_tts(value == VState.SPEAKING)
        await self.send_json({"type": "state", "value": value.value})

    async def handle_init(self, msg: dict) -> None:
        if engines is None or not engines.ready:
            with _boot_lock:
                detail = _boot.detail or "engines loading"
                progress = _boot.progress
            await self.send_json(
                {
                    "type": "error",
                    "code": "initializing",
                    "detail": detail,
                    "progress": progress,
                    "recoverable": True,
                }
            )
            return
        self.session_id = str(msg.get("session_id") or uuid.uuid4())
        hist = msg.get("history") or []
        self.history = [dict(m) for m in hist if isinstance(m, dict)]
        self.lang_hint = str(msg.get("lang_hint") or "auto")
        self.tts_engine = str(msg.get("tts_engine") or "auto")
        await self.set_state(VState.LISTENING)
        await self.send_json({"type": "session.ready"})
        get_field_pusher().start_session(src="phone")

    async def on_speech_start(self, msg: dict) -> None:
        ts = int(msg.get("ts") or time.time() * 1000)
        if self.state == VState.SPEAKING:
            await self._abort_turn(barge_in=True)
        elif self.state == VState.THINKING:
            await self._abort_turn(barge_in=False, thinking_rephrase=True)
        self._speech_start_ts = ts
        self._utterance.clear()
        self._accept_audio = True

    async def on_speech_end(self, msg: dict) -> None:
        self._accept_audio = False
        if self.state == VState.SPEAKING:
            dur = int(msg.get("ts") or time.time() * 1000) - self._speech_start_ts
            if dur < 300:
                return
        pcm = bytes(self._utterance)
        self._utterance.clear()
        if not pcm:
            return
        dur_ms = max(1, len(pcm) // 32)
        if self._thinking_user_buf:
            asr = _require_engines().transcribe(pcm, duration_ms=dur_ms)
            merged = (self._thinking_user_buf + "\n" + asr.text).strip()
            self._thinking_user_buf = ""
            asr.text = merged
        else:
            asr = _require_engines().transcribe(pcm, duration_ms=dur_ms)
        if VOICE_MOCK_ASR:
            asr.text = VOICE_MOCK_ASR
        await self.send_json(
            {
                "type": "asr.final",
                "text": asr.text,
                "lang": asr.lang,
                "emotion": asr.emotion,
                "event": asr.event,
                "duration_ms": asr.duration_ms,
            }
        )
        if not asr.text.strip():
            return
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
        self._abort.clear()
        self._ledger = TurnLedger()
        self._tts_idx = 0
        self._turn_task = asyncio.create_task(self._run_turn(asr.text))

    async def on_cancel(self) -> None:
        await self._abort_turn(barge_in=False)

    async def on_binary(self, data: bytes) -> None:
        if not data or not self._accept_audio:
            return
        if data[0] != CH_MIC:
            return
        pcm = data[1:]
        self._utterance.extend(pcm)
        get_field_pusher().enqueue_pcm(pcm)

    async def _abort_turn(self, *, barge_in: bool, thinking_rephrase: bool = False) -> None:
        self._abort.set()
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
            try:
                await self._turn_task
            except asyncio.CancelledError:
                pass
        spoken = self._ledger.spoken_text()
        if barge_in:
            self._interrupt_gate = True
            get_field_pusher().mark_barge()
            await self.send_json(
                {
                    "type": "interrupt.ack",
                    "aborted": {"llm": True, "tts": True},
                    "spoken_text": spoken,
                }
            )
        if thinking_rephrase and self._ledger.llm_text:
            self._thinking_user_buf = self._ledger.llm_text
        self._ledger = TurnLedger()
        self._tts_idx = 0
        await self.set_state(VState.LISTENING)

    async def _run_turn(self, user_text: str) -> None:
        await self.set_state(VState.THINKING)
        messages = list(self.history) + [{"role": "user", "content": user_text}]
        splitter = SentenceSplitter()
        finish_reason = "stop"
        first_tts = False
        try:
            async for delta, done, fr in self._stream_llm(messages):
                if self._abort.is_set():
                    finish_reason = "abort"
                    break
                if fr:
                    finish_reason = fr
                if delta:
                    self._ledger.llm_text += delta
                    await self.send_json({"type": "llm.delta", "text": delta})
                    for sentence in splitter.push(delta):
                        if self._abort.is_set():
                            break
                        ok = await self._speak_sentence(sentence)
                        if not ok:
                            finish_reason = "abort"
                            break
                        if not first_tts:
                            first_tts = True
                            await self.set_state(VState.SPEAKING)
                if done:
                    break
            if not self._abort.is_set():
                tail = splitter.flush()
                if tail:
                    ok = await self._speak_sentence(tail)
                    if not ok:
                        finish_reason = "abort"
                    if not first_tts and ok:
                        await self.set_state(VState.SPEAKING)
        except asyncio.CancelledError:
            finish_reason = "abort"
            raise
        except Exception as exc:
            logger.exception("turn failed")
            await self.send_json(
                {"type": "error", "code": "llm_fail", "detail": str(exc), "recoverable": True}
            )
            await self.set_state(VState.LISTENING)
            return

        if not self._abort.is_set():
            await self.send_json({"type": "llm.done", "finish_reason": finish_reason})
            await self.send_json({"type": "tts.done"})
            assistant = self._ledger.spoken_text() or self._ledger.llm_text
            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": assistant})
            await self.set_state(VState.LISTENING)

    async def _speak_sentence(self, sentence: str) -> bool:
        if VOICE_CFG.get("security", {}).get("per_sentence_check", True):
            hit = first_impersonation_hit(sentence)
            if hit:
                self._ledger.security_blocks += 1
                block_msg = {"type": "security.block", "pattern_id": hit, "sentence_idx": self._tts_idx}
                await self.send_json(block_msg)
                _audit_security(
                    {
                        "event": "security.block",
                        "session_id": self.session_id,
                        "pattern_id": hit,
                        "sentence": sentence,
                        "sentence_idx": self._tts_idx,
                        "tts_frames_sent": 0,
                    }
                )
                if self._ledger.security_blocks >= ABORT_BLOCKS:
                    await self.send_json(
                        {
                            "type": "error",
                            "code": "security_abort",
                            "detail": "impersonation threshold",
                            "recoverable": False,
                        }
                    )
                    return False
                return True
            gate = cleanroom_gate_check(sentence)
            if gate.get("blocked"):
                self._ledger.security_blocks += 1
                pid = (gate.get("patterns_matched") or ["cleanroom"])[0]
                block_msg = {"type": "security.block", "pattern_id": pid, "sentence_idx": self._tts_idx}
                await self.send_json(block_msg)
                _audit_security(
                    {
                        "event": "security.block",
                        "session_id": self.session_id,
                        "pattern_id": pid,
                        "sentence": sentence,
                        "sentence_idx": self._tts_idx,
                        "tts_frames_sent": 0,
                    }
                )
                if self._ledger.security_blocks >= ABORT_BLOCKS:
                    return False
                return True

        idx = self._tts_idx
        self._tts_idx += 1
        eng, route = _require_engines().resolve_tts_engine(sentence, engine=self.tts_engine)
        locale = classify_tts_locale(sentence)
        await self.send_json(
            {
                "type": "tts.sentence.start",
                "idx": idx,
                "text": sentence,
                "engine": eng,
                "route": route.reason,
                "locale": locale,
            }
        )
        self._ledger.pending_sentence = sentence
        try:
            for chunk in _require_engines().tts_pcm_chunks(sentence, engine=self.tts_engine):
                if self._abort.is_set() or self._interrupt_gate:
                    break
                await self.send_bytes(frame_tts(chunk))
            self._ledger.spoken_sentences.append(sentence)
            self._ledger.pending_sentence = None
            metrics = _require_engines().last_tts_synthesis
            await self.send_json({"type": "tts.sentence.end", "idx": idx, "metrics": metrics})
            self._interrupt_gate = False
            return True
        except Exception as exc:
            logger.exception("tts failed")
            await self.send_json(
                {"type": "error", "code": "tts_fail", "detail": str(exc), "recoverable": True}
            )
            return False

    async def _stream_llm(self, messages: list[dict]):
        if VOICE_MOCK_LLM:
            yield VOICE_MOCK_LLM, False, None
            yield "", True, "stop"
            return
        url = f"{CONFIG['openai_endpoint']}/chat/completions"
        prepared = _prepare_substrate_messages(messages)
        payload = _openai_chat_payload(
            prepared, stream=True, max_tokens=VOICE_MAX, model=CONFIG.get("openai_model")
        )
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if self._abort.is_set():
                        break
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        yield "", True, None
                        return
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choice = (obj.get("choices") or [{}])[0]
                    fr = choice.get("finish_reason")
                    delta = (choice.get("delta") or {}).get("content") or ""
                    if delta:
                        yield delta, False, None
                    if fr:
                        yield "", False, str(fr)
                yield "", True, None


@app.get("/health")
def health():
    with _boot_lock:
        st = _boot.status
        if st == "error":
            return JSONResponse(
                {
                    "status": "error",
                    "service": "grid-voice-daemon",
                    "progress": _boot.progress,
                    "phase": _boot.phase,
                    "detail": _boot.detail,
                    "error": _boot.error,
                    "port": PORT,
                    "bind_host": "127.0.0.1",
                },
                status_code=503,
            )
        if st != "ok" or engines is None:
            payload: dict[str, Any] = {
                "status": "initializing",
                "service": "grid-voice-daemon",
                "progress": _boot.progress,
                "phase": _boot.phase,
                "port": PORT,
                "bind_host": "127.0.0.1",
            }
            if _boot.detail:
                payload["detail"] = _boot.detail
            if _boot.asr_download is not None and _boot.asr_download < 1.0:
                payload["asr_download"] = _boot.asr_download
            return JSONResponse(payload)
        h = engines.health()
    return JSONResponse(
        {
            "status": "ok",
            "service": "grid-voice-daemon",
            "asr": h["asr"],
            "tts": h["tts"],
            "tts_engine": h["tts_engine"],
            "tts_active": h.get("tts_active"),
            "tts_route_policy": h.get("tts_route_policy"),
            "blockers": h.get("blockers", []),
            "warmup": h.get("warmup") or {},
            "port": PORT,
            "bind_host": "127.0.0.1",
        }
    )


@app.websocket("/ws/voice")
async def ws_voice(ws: WebSocket):
    await ws.accept()
    session = VoiceSession(ws)
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"] is not None:
                await session.on_binary(msg["bytes"])
                continue
            text = msg.get("text")
            if not text:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            typ = obj.get("type")
            if typ == "session.init":
                await session.handle_init(obj)
            elif typ == "speech.start":
                await session.on_speech_start(obj)
            elif typ == "speech.end":
                await session.on_speech_end(obj)
            elif typ == "turn.cancel":
                await session.on_cancel()
            elif typ == "ping":
                await session.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        get_field_pusher().end_session()
        if session._turn_task and not session._turn_task.done():
            session._turn_task.cancel()
        await session.set_state(VState.IDLE)


def main() -> None:
    import uvicorn

    host = "127.0.0.1"
    print(f"Grid Voice daemon listening http://{host}:{PORT}")
    uvicorn.run(app, host=host, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
