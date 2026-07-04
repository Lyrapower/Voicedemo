from __future__ import annotations

import math
import os
import struct

import numpy as np
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

VoiceSource = Literal["mic", "idle"]
AiSource = Literal["idle", "macos_say", "kokoro", "silent", "presence_echo"]

_VOICE_TTL_SEC = 2.5
_SPEAK_COOLDOWN_SEC = 4.0
_VOICE_TRIGGER_AMP = 0.14
# Daniel (UK male) — never fall back to legacy Samantha / novelty voices.
_VOICE_CANDIDATES = ("Daniel",)
# --- TTS 后端选择:auto = 优先 Kokoro,不可用时回退 macOS say ---
_TTS_BACKEND = os.environ.get("GARDEN_TTS_BACKEND", "auto").strip().lower()  # auto|kokoro|say
_KOKORO_MODEL = os.environ.get(
    "GARDEN_KOKORO_MODEL",
    str(Path.home() / ".cache" / "kokoro" / "kokoro-v1.0.onnx"),
)
_KOKORO_VOICES = os.environ.get(
    "GARDEN_KOKORO_VOICES",
    str(Path.home() / ".cache" / "kokoro" / "voices-v1.0.bin"),
)
_KOKORO_VOICE = os.environ.get("GARDEN_KOKORO_VOICE", "af_heart")
_KOKORO_SPEED = float(os.environ.get("GARDEN_KOKORO_SPEED", "1.0"))
_kokoro_engine = None
_kokoro_failed = False
_KOKORO_LOCK = threading.Lock()


def _get_kokoro():
    """惰性加载 Kokoro-82M(kokoro-onnx)。模型/包缺失时静默回退到 say。"""
    global _kokoro_engine, _kokoro_failed
    if _kokoro_engine is not None or _kokoro_failed:
        return _kokoro_engine
    with _KOKORO_LOCK:
        if _kokoro_engine is not None or _kokoro_failed:
            return _kokoro_engine
        if _TTS_BACKEND == "say":
            _kokoro_failed = True
            return None
        try:
            from kokoro_onnx import Kokoro  # pip install kokoro-onnx

            if not Path(_KOKORO_MODEL).is_file() or not Path(_KOKORO_VOICES).is_file():
                raise FileNotFoundError("kokoro model files missing")
            _kokoro_engine = Kokoro(_KOKORO_MODEL, _KOKORO_VOICES)
        except Exception:
            _kokoro_failed = True
            _kokoro_engine = None
        return _kokoro_engine


def _kokoro_to_wav(text: str, wav_path: Path) -> bool:
    """Kokoro 合成 → 16-bit mono WAV。成功返回 True。"""
    engine = _get_kokoro()
    if engine is None:
        return False
    try:
        samples, sample_rate = engine.create(text, voice=_KOKORO_VOICE, speed=_KOKORO_SPEED)
        pcm = np.clip(np.asarray(samples, dtype=np.float64) * 32767.0, -32768, 32767).astype(np.int16)
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(sample_rate))
            wf.writeframes(pcm.tobytes())
        return True
    except Exception:
        return False
_TTS_RATE = int(os.environ.get("GARDEN_TTS_RATE", "155"))
_MIN_THINK_SEC = float(os.environ.get("GARDEN_MIN_THINK_SEC", "1.65"))
_GARDEN_GATEWAY_URL = os.environ.get("GARDEN_GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
_LLM_DIALOGUE = os.environ.get("GARDEN_LLM_DIALOGUE", "1").strip().lower() in (
    "1",
    "true",
    "on",
    "yes",
)
_TTS_ENABLED = os.environ.get("GARDEN_TTS_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "off",
    "no",
)
_AUTO_SPEAK_ON_MIC = os.environ.get("GARDEN_TTS_AUTO_ON_MIC", "0").strip().lower() in (
    "1",
    "true",
    "on",
    "yes",
)
_RESOLVED_VOICE: str | None = None
_VOICE_LOCK = threading.Lock()


@dataclass
class VoiceState:
    voice_freq: float = 0.0
    voice_amp: float = 0.0
    updated_at: float = 0.0
    source: VoiceSource = "idle"


@dataclass
class AiFrame:
    t: float
    freq: float
    amp: float


@dataclass
class GardenLiveState:
    voice: VoiceState = field(default_factory=VoiceState)
    echo_freq: float = 0.0   # presence echo 的当前频率(慢速跟随,不再精确镜像)
    echo_at: float = 0.0
    ai_frames: list[AiFrame] = field(default_factory=list)
    ai_started_at: float = 0.0
    ai_duration: float = 0.0
    ai_source: AiSource = "idle"
    ai_text: str = ""
    speaking: bool = False
    synthesizing: bool = False  # TTS 合成中 = thinking(真实信号,不是动画)
    last_speak_at: float = 0.0
    last_latency_ms: float = 18.0
    presence_enabled: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


STATE = GardenLiveState()


def tts_status() -> dict[str, str | bool]:
    voice = _resolve_voice()
    kokoro_ok = _get_kokoro() is not None
    backend = "kokoro" if kokoro_ok else ("macos_tts" if _TTS_ENABLED and voice else "silent")
    return {
        "backend": backend,
        "kokoro_voice": _KOKORO_VOICE if kokoro_ok else "",
        "tts_enabled": bool(_TTS_ENABLED and voice),
        "tts_voice": voice or "",
        "llm_stream": "disabled",
        "auto_speak_on_mic": _AUTO_SPEAK_ON_MIC,
        "presence_enabled": STATE.presence_enabled,
    }


def set_presence(enabled: bool) -> dict[str, bool]:
    with STATE.lock:
        STATE.presence_enabled = bool(enabled)
        return {"enabled": STATE.presence_enabled}


def _voice_installed(name: str) -> bool:
    try:
        proc = subprocess.run(
            ["say", "-v", name, "ok"],
            capture_output=True,
            timeout=4,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _resolve_voice() -> str | None:
    global _RESOLVED_VOICE
    if not _TTS_ENABLED:
        return None
    with _VOICE_LOCK:
        if _RESOLVED_VOICE is not None:
            return _RESOLVED_VOICE or None
        preferred = os.environ.get("GARDEN_TTS_VOICE", "").strip()
        if preferred and _voice_installed(preferred):
            _RESOLVED_VOICE = preferred
            return preferred
        for candidate in _VOICE_CANDIDATES:
            if _voice_installed(candidate):
                _RESOLVED_VOICE = candidate
                return candidate
        _RESOLVED_VOICE = ""
        return None


def _voice_snapshot(now: float) -> tuple[float, VoiceSource]:
    age = now - STATE.voice.updated_at
    if age <= _VOICE_TTL_SEC and STATE.voice.voice_freq > 30:
        return STATE.voice.voice_freq, "mic"
    return 0.0, "idle"


def _ai_snapshot(now: float) -> tuple[float, float, AiSource]:
    if not STATE.speaking or not STATE.ai_frames:
        return 0.0, 0.0, "idle"
    src = STATE.ai_source if STATE.ai_source in ("macos_say", "kokoro") else "macos_say"
    elapsed = max(0.0, now - STATE.ai_started_at)
    if elapsed > STATE.ai_duration:
        return STATE.ai_frames[-1].freq, 0.06, src
    frame = STATE.ai_frames[0]
    for item in STATE.ai_frames:
        if item.t <= elapsed:
            frame = item
        else:
            break
    return frame.freq, frame.amp, src


def report_voice(voice_freq: float, voice_amp: float) -> None:
    now = time.time()
    with STATE.lock:
        STATE.voice.voice_freq = float(voice_freq)
        STATE.voice.voice_amp = float(voice_amp)
        STATE.voice.updated_at = now
        STATE.voice.source = "mic"
        if (
            _AUTO_SPEAK_ON_MIC
            and _TTS_ENABLED
            and _resolve_voice()
            and voice_amp >= _VOICE_TRIGGER_AMP
            and not STATE.speaking
            and (now - STATE.last_speak_at) >= _SPEAK_COOLDOWN_SEC
        ):
            threading.Thread(
                target=_speak_worker,
                args=(_build_reply(voice_freq),),
                daemon=True,
            ).start()


def speak_now(text: str | None = None) -> dict[str, str]:
    if not (text or "").strip():
        return {"status": "noop", "text": ""}
    now = time.time()
    voice = _resolve_voice()
    if not _TTS_ENABLED or not voice:
        return {"status": "disabled", "text": "", "reason": "tts_off_or_no_voice"}
    with STATE.lock:
        if STATE.speaking:
            return {"status": "busy", "text": STATE.ai_text}
        if (now - STATE.last_speak_at) < 1.0:
            return {"status": "cooldown", "text": ""}
        prompt = text.strip()
    threading.Thread(target=_dialogue_speak_worker, args=(prompt,), daemon=True).start()
    return {
        "status": "queued",
        "text": prompt,
        "voice": voice,
        "llm": _llm_dialogue_active(),
        "gateway": _GARDEN_GATEWAY_URL,
    }


def _dialogue_speak_worker(prompt: str) -> None:
    with STATE.lock:
        STATE.synthesizing = True
    reply = _resolve_llm_reply(prompt)
    _speak_worker(reply)


def telemetry_payload() -> dict[str, float | str | bool]:
    now = time.time()
    with STATE.lock:
        if STATE.speaking and STATE.ai_duration > 0 and (now - STATE.ai_started_at) > STATE.ai_duration + 0.2:
            STATE.speaking = False
            STATE.ai_source = "idle"
        voice_freq, voice_source = _voice_snapshot(now)
        ai_freq, ai_amp, ai_source = _ai_snapshot(now)
        if (
            ai_source == "idle"
            and STATE.presence_enabled
            and voice_source == "mic"
            and voice_freq > 30
        ):
            # 慢速跟随(时间常数 ~2.2s)而非精确镜像:
            # 你的音高移动时 echo 滞后,产生真实拍频;稳定保持时才收敛对齐。
            # 这让 coherence 成为需要"调音"才能达到的时刻,而不是恒真。
            dt = min(1.0, max(0.0, now - STATE.echo_at)) if STATE.echo_at > 0 else 0.0
            if STATE.echo_freq <= 0:
                STATE.echo_freq = voice_freq * 0.82  # 起始略低,留出靠近的过程
            else:
                alpha = 1.0 - math.exp(-dt / 2.2)
                STATE.echo_freq += (voice_freq - STATE.echo_freq) * alpha
            STATE.echo_at = now
            ai_freq = STATE.echo_freq
            ai_amp = min(1.0, max(0.03, STATE.voice.voice_amp * 0.75))
            ai_source = "presence_echo"
        elif voice_source != "mic":
            STATE.echo_freq = 0.0  # 静音后重置,下次开口重新开始靠近
            STATE.echo_at = 0.0
        latency = STATE.last_latency_ms
        speaking = STATE.speaking
        synthesizing = STATE.synthesizing
        ai_text = STATE.ai_text
        presence_on = STATE.presence_enabled
    active = voice_source == "mic" or ai_source != "idle" or speaking
    if speaking:
        ai_state = "speaking"
    elif synthesizing:
        ai_state = "thinking"  # 合成期间;接入本地 LLM 后生成循环也走这里
    elif voice_source == "mic":
        ai_state = "listening"
    else:
        ai_state = "idle"
    return {
        "t": now,
        "aiState": ai_state,
        "mode": "macos_tts" if _TTS_ENABLED and _resolve_voice() else "silent",
        "voiceSource": voice_source,
        "voiceFreq": voice_freq,
        "aiSource": ai_source,
        "aiFreq": ai_freq,
        "aiAmplitude": ai_amp,
        "latencyMs": latency if active else 0.0,
        "speaking": speaking,
        "aiText": ai_text,
        "ttsVoice": _resolve_voice() or "",
        "llmDialogue": _llm_dialogue_active(),
        "gatewayUrl": _GARDEN_GATEWAY_URL,
        "active": active,
        "presenceEnabled": presence_on,
    }


_GATEWAY_CACHE = {"ok": False, "at": 0.0}


def _llm_dialogue_active() -> bool:
    if not _LLM_DIALOGUE:
        return False
    now = time.time()
    if now - _GATEWAY_CACHE["at"] < 8.0:
        return _GATEWAY_CACHE["ok"]
    try:
        from .garden_gateway import gateway_reachable

        ok = gateway_reachable()
    except Exception:
        ok = False
    _GATEWAY_CACHE["ok"] = ok
    _GATEWAY_CACHE["at"] = now
    return ok


def _resolve_llm_reply(prompt: str | None = None, voice_freq: float = 0.0) -> str:
    """9B via Grid gateway when up; else short presence line."""
    if _llm_dialogue_active():
        from .garden_gateway import gateway_chat

        user_prompt = (prompt or "").strip()
        if not user_prompt:
            user_prompt = (
                "Voice Garden is listening. "
                "Reply in one or two short spoken sentences, warm and present."
            )
        reply = gateway_chat(user_prompt)
        if reply:
            return reply
    _ = voice_freq
    return (prompt or "I'm here.").strip() or "I'm here."


def _build_reply(voice_freq: float) -> str:
    return _resolve_llm_reply(voice_freq=voice_freq)


def _analyze_wav(path: Path) -> tuple[list[AiFrame], float]:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sample_width = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())

    if channels > 1:
        frames = _to_mono(frames, sample_width, channels)

    if sample_width != 2:
        frames = _convert_width(frames, sample_width, 2)
        sample_width = 2

    total_samples = len(frames) // sample_width
    duration = total_samples / max(1, sample_rate)
    window = max(512, sample_rate // 20)
    hop = max(256, window // 2)
    out: list[AiFrame] = []

    for start in range(0, max(1, total_samples - window), hop):
        chunk = frames[start * sample_width : (start + window) * sample_width]
        if len(chunk) < window * sample_width:
            break
        rms = _rms(chunk, sample_width) / 32768.0
        amp = min(1.0, max(0.03, rms * 2.4))
        freq = _dominant_freq(chunk, sample_rate)
        out.append(AiFrame(t=start / sample_rate, freq=freq, amp=amp))

    if not out:
        out = [AiFrame(t=0.0, freq=220.0, amp=0.12)]
    return out, duration


_WIDTH_DTYPE = {1: np.uint8, 2: np.int16, 4: np.int32}


def _frames_to_array(frames: bytes, sample_width: int) -> "np.ndarray":
    """Decode PCM bytes to a float64 array of signed samples."""
    dtype = _WIDTH_DTYPE.get(sample_width)
    if dtype is None:
        return np.zeros(0, dtype=np.float64)
    n = len(frames) // sample_width
    arr = np.frombuffer(frames, dtype=dtype, count=n).astype(np.float64)
    if sample_width == 1:
        arr -= 128.0  # 8-bit WAV is unsigned; recenter
    return arr


def _array_to_frames(arr: "np.ndarray", sample_width: int) -> bytes:
    if sample_width == 1:
        return (np.clip(arr, -128, 127) + 128).astype(np.uint8).tobytes()
    if sample_width == 4:
        return np.clip(arr, -2147483648, 2147483647).astype(np.int32).tobytes()
    return np.clip(arr, -32768, 32767).astype(np.int16).tobytes()


def _to_mono(frames: bytes, sample_width: int, channels: int) -> bytes:
    if channels == 1:
        return frames
    arr = _frames_to_array(frames, sample_width)
    usable = (arr.size // channels) * channels
    mono = arr[:usable].reshape(-1, channels).mean(axis=1)
    return _array_to_frames(mono, sample_width)


def _convert_width(frames: bytes, from_width: int, to_width: int) -> bytes:
    if from_width == to_width:
        return frames
    arr = _frames_to_array(frames, from_width)
    # Rescale into the target width's range (shift by bit-depth difference)
    arr *= 2.0 ** (8 * (to_width - from_width))
    return _array_to_frames(arr, to_width)


def _read_sample(data: bytes, sample_width: int) -> int:
    if sample_width == 1:
        return data[0] - 128
    if sample_width == 2:
        return struct.unpack("<h", data)[0]
    if sample_width == 4:
        return int(struct.unpack("<i", data)[0] / 65536)
    return 0


def _write_sample(value: int, sample_width: int) -> bytes:
    if sample_width == 1:
        return bytes([max(0, min(255, value + 128))])
    if sample_width == 2:
        return struct.pack("<h", max(-32768, min(32767, value)))
    if sample_width == 4:
        return struct.pack("<i", max(-2147483648, min(2147483647, value * 65536)))
    return b"\x00\x00"


def _rms(chunk: bytes, sample_width: int) -> float:
    if not chunk:
        return 0.0
    arr = _frames_to_array(chunk, sample_width)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr * arr)))


def _dominant_freq(chunk: bytes, sample_rate: int) -> float:
    n = len(chunk) // 2
    if n < 4:
        return 220.0
    s = np.frombuffer(chunk, dtype=np.int16, count=n).astype(np.float64)
    # Vectorized zero-crossing count (matches the original prev<=0<cur / prev>=0>cur logic)
    prev = s[:-1]
    cur = s[1:]
    crossing = int(np.count_nonzero(((prev <= 0) & (cur > 0)) | ((prev >= 0) & (cur < 0))))
    seconds = n / max(1, sample_rate)
    if seconds <= 0 or crossing < 2:
        return 220.0
    freq = crossing / (2 * seconds)
    return float(max(90.0, min(900.0, freq)))


def _speak_worker(text: str) -> None:
    started = time.perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix="garden_tts_"))
    aiff = tmp / "reply.aiff"
    wav = tmp / "reply.wav"
    with STATE.lock:
        STATE.synthesizing = True  # → aiState = "thinking"
    try:
        used_kokoro = _kokoro_to_wav(text, wav)
        if not used_kokoro:
            voice = _resolve_voice()
            if not voice:
                return
            subprocess.run(
                ["say", "-v", voice, "-r", str(_TTS_RATE), "-o", str(aiff), text],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16", str(aiff), str(wav)],
                check=True,
                capture_output=True,
            )
        frames, duration = _analyze_wav(wav)
        elapsed = time.perf_counter() - started
        if elapsed < _MIN_THINK_SEC:
            time.sleep(_MIN_THINK_SEC - elapsed)
        now = time.time()
        with STATE.lock:
            STATE.ai_frames = frames
            STATE.ai_duration = duration
            STATE.ai_started_at = now
            STATE.ai_text = text
            STATE.ai_source = "kokoro" if used_kokoro else "macos_say"
            STATE.speaking = True
            STATE.synthesizing = False  # thinking → speaking
            STATE.last_speak_at = now
            STATE.last_latency_ms = max(8.0, (time.perf_counter() - started) * 1000.0)
        subprocess.run(
            ["afplay", str(wav if used_kokoro else aiff)],
            check=False,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError, wave.Error):
        with STATE.lock:
            STATE.speaking = False
            STATE.synthesizing = False
            STATE.ai_source = "idle"
    finally:
        with STATE.lock:
            STATE.synthesizing = False
            if STATE.speaking:
                STATE.speaking = False
                STATE.ai_source = "idle"
        for path in (aiff, wav):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            tmp.rmdir()
        except OSError:
            pass
