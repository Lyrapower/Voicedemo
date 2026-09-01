"""Local media preprocessing for POST /task/expanded (ffmpeg + optional ASR)."""
from __future__ import annotations

import base64
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from io import BytesIO
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_VIDEO_FRAMES = 6
_asr_lock = threading.Lock()
_asr_engine: Any = None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _write_temp(data: bytes, suffix: str) -> Path:
    fd, name = tempfile.mkstemp(suffix=suffix)
    path = Path(name)
    with open(fd, "wb") as fh:
        fh.write(data)
    return path


def _run_ffmpeg(args: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def wav_bytes_to_pcm16(wav_bytes: bytes) -> tuple[bytes, int]:
    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError("expected mono pcm16 wav")
        rate = wf.getframerate()
        return wf.readframes(wf.getnframes()), rate


def _get_asr_engine(config: dict[str, Any]) -> Any | None:
    global _asr_engine
    if _asr_engine is not None:
        return _asr_engine
    with _asr_lock:
        if _asr_engine is not None:
            return _asr_engine
        try:
            from voice_engines import VoiceEngines

            eng = VoiceEngines(config.get("voice") or {})
            eng._init_asr()
            if eng._asr_name in ("unavailable", "unloaded"):
                return None
            _asr_engine = eng
            return _asr_engine
        except Exception as exc:
            logger.warning("expanded ASR init failed: %s", exc)
            return None


def transcribe_wav_bytes(wav_bytes: bytes, config: dict[str, Any]) -> tuple[str, str]:
    eng = _get_asr_engine(config)
    if eng is None:
        return "", "asr_unavailable"
    try:
        pcm, rate = wav_bytes_to_pcm16(wav_bytes)
    except Exception as exc:
        return "", f"wav_decode:{exc}"
    result = eng.transcribe(pcm, sample_rate=rate, duration_ms=int(len(pcm) / (rate * 2) * 1000))
    text = str(getattr(result, "text", "") or "").strip()
    engine = str(getattr(result, "engine", "") or eng._asr_name)
    return text, engine


def audio_b64_to_wav(b64: str, *, mime: str = "audio/mp4") -> tuple[bytes | None, str | None]:
    if not ffmpeg_available():
        return None, "ffmpeg_missing"
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception as exc:
        return None, f"b64_decode:{exc}"
    src = _write_temp(raw, suffix=_suffix_for_mime(mime))
    out = Path(tempfile.mktemp(suffix=".wav"))
    try:
        proc = _run_ffmpeg(["-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-f", "wav", str(out)])
        if proc.returncode != 0 or not out.is_file():
            return None, (proc.stderr or "ffmpeg_audio_failed")[:200]
        return out.read_bytes(), None
    finally:
        src.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def extract_video_frames(b64: str, *, max_frames: int = _MAX_VIDEO_FRAMES) -> tuple[list[dict[str, str]], str | None]:
    if not ffmpeg_available():
        return [], "ffmpeg_missing"
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception as exc:
        return [], f"b64_decode:{exc}"
    src = _write_temp(raw, suffix=".mp4")
    frames: list[dict[str, str]] = []
    try:
        duration_proc = _run_ffmpeg(["-i", str(src)])
        duration = _probe_duration(duration_proc.stderr or "")
        if duration <= 0:
            duration = 6.0
        step = max(duration / max(1, max_frames), 0.5)
        for i in range(max_frames):
            ts = min(i * step, max(duration - 0.1, 0))
            out = Path(tempfile.mktemp(suffix=f"_f{i}.jpg"))
            proc = _run_ffmpeg(
                ["-y", "-ss", f"{ts:.2f}", "-i", str(src), "-frames:v", "1", "-q:v", "4", str(out)]
            )
            if proc.returncode == 0 and out.is_file() and out.stat().st_size > 100:
                frames.append(
                    {
                        "mime": "image/jpeg",
                        "base64": base64.b64encode(out.read_bytes()).decode("ascii"),
                    }
                )
            out.unlink(missing_ok=True)
        return frames, None
    finally:
        src.unlink(missing_ok=True)


def extract_video_audio_wav(b64: str) -> tuple[bytes | None, str | None]:
    if not ffmpeg_available():
        return None, "ffmpeg_missing"
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception as exc:
        return None, f"b64_decode:{exc}"
    src = _write_temp(raw, suffix=".mp4")
    out = Path(tempfile.mktemp(suffix=".wav"))
    try:
        proc = _run_ffmpeg(
            ["-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(out)]
        )
        if proc.returncode != 0 or not out.is_file() or out.stat().st_size < 1000:
            return None, (proc.stderr or "no_audio_track")[:200]
        return out.read_bytes(), None
    finally:
        src.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def preprocess_audio_asset(
    b64: str,
    name: str,
    config: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    meta: dict[str, Any] = {"name": name}
    wav, err = audio_b64_to_wav(b64)
    if err or not wav:
        meta["error"] = err or "empty"
        return f"【音频 {name}】本地未能转写(transcript 不可用)。", meta
    text, engine = transcribe_wav_bytes(wav, config)
    meta["asr_engine"] = engine
    if text:
        meta["transcript_chars"] = len(text)
        return f"【音频 {name} · transcript】\n{text[:8000]}", meta
    return f"【音频 {name}】ASR 未产出文本({engine})。", meta


def preprocess_video_asset(
    b64: str,
    name: str,
    config: dict[str, Any],
) -> tuple[list[str], list[dict[str, str]], dict[str, Any]]:
    meta: dict[str, Any] = {"name": name}
    text_blocks: list[str] = []
    frames, ferr = extract_video_frames(b64)
    if ferr:
        meta["frame_error"] = ferr
    else:
        meta["frame_count"] = len(frames)
    wav, aerr = extract_video_audio_wav(b64)
    if aerr:
        meta["audio_error"] = aerr
    elif wav:
        text, engine = transcribe_wav_bytes(wav, config)
        meta["asr_engine"] = engine
        if text:
            meta["transcript_chars"] = len(text)
            text_blocks.append(f"【视频 {name} · transcript】\n{text[:8000]}")
    if frames:
        text_blocks.append(f"【视频 {name} · 关键帧】已抽 {len(frames)} 帧供视觉参考。")
    if not text_blocks and not frames:
        text_blocks.append(f"【视频 {name}】本地未能抽帧/转写。")
    return text_blocks, frames, meta


def _suffix_for_mime(mime: str) -> str:
    m = (mime or "").lower()
    if "mp4" in m or "m4a" in m:
        return ".m4a"
    if "mpeg" in m or "mp3" in m:
        return ".mp3"
    if "wav" in m:
        return ".wav"
    return ".bin"


def _probe_duration(stderr: str) -> float:
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if not m:
        return 0.0
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s
