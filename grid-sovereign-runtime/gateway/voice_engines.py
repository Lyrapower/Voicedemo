"""ASR/TTS engine adapters — local only, zero egress. Spec §0: CosyVoice2 primary, Kokoro fallback."""
from __future__ import annotations

import io
import logging
import os
import re
import statistics
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

ProgressFn = Callable[..., None]

logger = logging.getLogger(__name__)

CH_MIC = 0x01
CH_TTS = 0x02

ROOT = Path(__file__).resolve().parents[1]
COSYVOICE_REPO = ROOT / "third_party" / "CosyVoice"
DEFAULT_COSYVOICE_MODEL = ROOT / "pretrained_models" / "CosyVoice2-0.5B"
GRID_MODEL_CACHE = ROOT / "data" / "model_cache"
SENSEVOICE_HUB_ID = "iic/SenseVoiceSmall"
WARMUP_TEXT = "打开Grid的voice测试模式"
_SENSE_TAG_RE = re.compile(r"<\|([^|]+)\|>")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_SENSEVOICE_MODEL_BYTES = 936 * 1024 * 1024  # hub logs: model.pt ~936M
WARMUP_RUNS = 3
_COSYVOICE_DEVICE_PATCHED = False
_MODEL_CACHE_CONFIGURED = False


def configure_model_cache() -> Path:
    """Pin modelscope/HF cache under repo data/ — survives reboot, supports resume."""
    global _MODEL_CACHE_CONFIGURED
    ms_cache = GRID_MODEL_CACHE / "modelscope"
    hf_cache = GRID_MODEL_CACHE / "huggingface"
    ms_cache.mkdir(parents=True, exist_ok=True)
    hf_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MODELSCOPE_CACHE", str(ms_cache))
    os.environ.setdefault("HF_HOME", str(hf_cache))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(hf_cache / "hub"))
    if not _MODEL_CACHE_CONFIGURED:
        legacy_ms = Path.home() / ".cache" / "modelscope" / "models" / "iic--SenseVoiceSmall"
        target_ms = ms_cache / "models" / "iic--SenseVoiceSmall"
        if legacy_ms.is_dir() and not target_ms.exists():
            target_ms.parent.mkdir(parents=True, exist_ok=True)
            target_ms.symlink_to(legacy_ms.resolve())
            logger.info("linked legacy SenseVoice cache %s -> %s", legacy_ms, target_ms)
        _MODEL_CACHE_CONFIGURED = True
    return ms_cache


def sensevoice_snapshot_dir() -> Path | None:
    configure_model_cache()
    ms_root = Path(os.environ["MODELSCOPE_CACHE"]) / "models" / "iic--SenseVoiceSmall" / "snapshots"
    if not ms_root.is_dir():
        return None
    snaps = sorted((p for p in ms_root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    return snaps[0] if snaps else None


def sensevoice_model_pt_path() -> Path | None:
    snap = sensevoice_snapshot_dir()
    if not snap:
        return None
    for name in ("model.pt", "model.pt.incomplete"):
        pt = snap / name
        if pt.is_file():
            return pt
    return None


def _parse_sensevoice_output(raw: str) -> tuple[str, str, str | None, str | None]:
    tags = _SENSE_TAG_RE.findall(raw or "")
    text = _SENSE_TAG_RE.sub("", raw or "").strip()
    lang = "mixed"
    emotion: str | None = "neutral"
    event: str | None = "speech"
    emo_set = {
        "neutral",
        "happy",
        "sad",
        "angry",
        "fearful",
        "disgusted",
        "surprised",
        "unknown",
    }
    evt_set = {"speech", "bgm", "applause", "laughter", "cry", "sneeze", "cough", "event"}
    for tag in tags:
        tl = tag.lower()
        if tl in ("zh", "en", "yue", "ja", "ko", "auto"):
            lang = tl if tl in ("zh", "en") else "mixed"
        elif tl in emo_set:
            emotion = tl
        elif tl in evt_set or tl == "withitn":
            if tl != "withitn":
                event = tl
    if not text:
        emotion = None
        event = None
    return text, lang, emotion, event


def is_pure_english_sentence(text: str) -> bool:
    """True when sentence has Latin words and no CJK — safe for Kokoro G2P."""
    stripped = (text or "").strip()
    if not stripped or _CJK_RE.search(stripped):
        return False
    return bool(_LATIN_WORD_RE.search(stripped))


def classify_tts_locale(text: str) -> str:
    """Classify sentence locale for runtime TTS routing: zh | en | mixed."""
    stripped = (text or "").strip()
    if not stripped:
        return "mixed"
    if is_pure_english_sentence(stripped):
        return "en"
    has_cjk = bool(_CJK_RE.search(stripped))
    has_latin = bool(_LATIN_WORD_RE.search(stripped))
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    return "mixed"


@dataclass
class AsrResult:
    text: str
    lang: str = "mixed"
    emotion: str | None = None
    event: str | None = None
    duration_ms: int = 0
    engine: str = "unknown"


@dataclass
class TtsRoute:
    engine: str
    fallback_from: str | None = None
    reason: str | None = None


@dataclass
class TtsSynthesisStats:
    engine: str
    locale: str
    route: str
    device: str | None = None
    first_packet_ms: float | None = None
    elapsed_sec: float | None = None
    audio_sec: float | None = None
    rtf: float | None = None
    fallback_from: str | None = None
    fallback_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "locale": self.locale,
            "route": self.route,
            "device": self.device,
            "first_packet_ms": self.first_packet_ms,
            "elapsed_sec": self.elapsed_sec,
            "audio_sec": self.audio_sec,
            "rtf": self.rtf,
            "fallback_from": self.fallback_from,
            "fallback_reason": self.fallback_reason,
        }


class TtsUnavailableError(RuntimeError):
    def __init__(self, message: str, *, blockers: list[str] | None = None) -> None:
        super().__init__(message)
        self.blockers = blockers or []


def _pcm16_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _float_tensor_to_pcm16(tensor, sample_rate: int) -> tuple[bytes, int]:
    import numpy as np
    import torch

    if isinstance(tensor, torch.Tensor):
        arr = tensor.detach().cpu().numpy()
    else:
        arr = np.asarray(tensor, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.reshape(-1)
    arr = np.clip(arr.astype(np.float32), -1.0, 1.0)
    pcm = (arr * 32767.0).astype(np.int16).tobytes()
    return pcm, int(sample_rate)


def _resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    if src_rate == dst_rate or not pcm:
        return pcm
    import numpy as np

    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if len(x) < 2:
        return pcm
    dst_len = max(1, int(len(x) * dst_rate / src_rate))
    src_idx = np.linspace(0, len(x) - 1, dst_len)
    y = np.interp(src_idx, np.arange(len(x)), x)
    return y.astype(np.int16).tobytes()


def _enable_mps_fallback() -> None:
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def _resolve_cosyvoice_device():
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _patch_cosyvoice_device() -> str:
    """Runtime monkeypatch — CosyVoice upstream only picks cuda|cpu; route Mac to MPS."""
    global _COSYVOICE_DEVICE_PATCHED
    _enable_mps_fallback()
    chosen = _resolve_cosyvoice_device()
    if _COSYVOICE_DEVICE_PATCHED:
        return str(chosen)

    import torch
    from contextlib import nullcontext

    from cosyvoice.cli import frontend as cv_frontend
    from cosyvoice.cli import model as cv_model

    def _apply_model_device(obj: object) -> None:
        obj.device = chosen  # type: ignore[attr-defined]
        if not torch.cuda.is_available():
            obj.llm_context = nullcontext()  # type: ignore[attr-defined]

    def _wrap_model_init(orig):
        def patched(self, *args, **kwargs):
            orig(self, *args, **kwargs)
            _apply_model_device(self)

        patched._grid_device_patched = True  # type: ignore[attr-defined]
        return patched

    def _wrap_frontend_init(orig):
        def patched(self, *args, **kwargs):
            orig(self, *args, **kwargs)
            self.device = chosen  # type: ignore[attr-defined]

        patched._grid_device_patched = True  # type: ignore[attr-defined]
        return patched

    for cls in (cv_model.CosyVoiceModel, cv_model.CosyVoice2Model, cv_model.CosyVoice3Model):
        if not getattr(cls.__init__, "_grid_device_patched", False):
            cls.__init__ = _wrap_model_init(cls.__init__)

    if not getattr(cv_frontend.CosyVoiceFrontEnd.__init__, "_grid_device_patched", False):
        cv_frontend.CosyVoiceFrontEnd.__init__ = _wrap_frontend_init(
            cv_frontend.CosyVoiceFrontEnd.__init__
        )

    _COSYVOICE_DEVICE_PATCHED = True
    logger.info(
        "CosyVoice device monkeypatch: %s (PYTORCH_ENABLE_MPS_FALLBACK=%s)",
        chosen,
        os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"),
    )
    return str(chosen)


class VoiceEngines:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg or {}
        self._asr_name = "unavailable"
        self._tts_primary = "cosyvoice2"
        self._tts_active = "unavailable"
        self._cosyvoice = None
        self._cosyvoice_speaker: str | None = None
        self._cosyvoice_prompt_wav: str | None = None
        self._cosyvoice_sr = 24000
        self._kokoro = None
        self._whisper = None
        self._sensevoice = None
        self.blockers: list[str] = []
        self._warmup_stats: dict = {}
        self._last_tts_synthesis: TtsSynthesisStats | None = None
        self._ready = False

    @staticmethod
    def sensevoice_download_fraction() -> float | None:
        """Best-effort partial download ratio for iic/SenseVoiceSmall model.pt."""
        pt = sensevoice_model_pt_path()
        if pt is None:
            return None
        return min(1.0, pt.stat().st_size / _SENSEVOICE_MODEL_BYTES)

    def bootstrap(self, on_progress: ProgressFn | None = None) -> None:
        configure_model_cache()

        def prog(phase: str, progress: float, detail: str = "", **extra: Any) -> None:
            if on_progress:
                on_progress(phase, progress, detail, **extra)

        prog("cosyvoice", 0.02, "loading CosyVoice2")
        self._init_cosyvoice()
        prog("cosyvoice", 0.30, "CosyVoice2 loaded" if self._cosyvoice else "CosyVoice2 skipped")
        prog("kokoro", 0.32, "loading Kokoro fallback")
        self._init_kokoro()
        prog("kokoro", 0.35, f"TTS active: {self._tts_active}")
        if self._tts_active == "cosyvoice2":
            prog("warmup", 0.38, "TTS warmup")
            self._warmup_stats = self.warmup_tts()
            logger.info("voice TTS warmup: %s", self._warmup_stats)
            prog("warmup", 0.50, "TTS warmup done")
        else:
            prog("warmup", 0.50, "TTS warmup skipped")
        self._init_asr_with_progress(prog)
        self._ready = True
        prog("ready", 1.0, f"ASR={self._asr_name} TTS={self._tts_active}")

    def _init_asr_with_progress(self, prog: ProgressFn) -> None:
        stop = threading.Event()

        def poller() -> None:
            while not stop.wait(1.0):
                frac = self.sensevoice_download_fraction()
                if frac is not None and frac < 1.0:
                    prog(
                        "asr",
                        0.50 + 0.45 * frac,
                        f"downloading SenseVoice model.pt {frac:.0%}",
                        asr_download=frac,
                    )
                elif frac == 1.0:
                    prog("asr", 0.95, "loading SenseVoice weights", asr_download=1.0)
                else:
                    prog("asr", 0.55, "loading ASR")

        t = threading.Thread(target=poller, daemon=True, name="sensevoice-progress")
        t.start()
        try:
            prog("asr", 0.52, "initializing ASR")
            self._init_asr()
        finally:
            stop.set()
            t.join(timeout=2.0)

    @property
    def ready(self) -> bool:
        return self._ready

    def _probe_cosyvoice_blockers(self) -> list[str]:
        blockers: list[str] = []
        if not COSYVOICE_REPO.is_dir():
            blockers.append(f"CosyVoice repo missing at {COSYVOICE_REPO}")
        try:
            import torch  # noqa: F401
        except Exception as exc:
            blockers.append(f"torch not importable: {exc}")
        tts_cfg = (self.cfg.get("tts") or {}).get("cosyvoice") or {}
        model_dir = Path(tts_cfg.get("model_dir") or DEFAULT_COSYVOICE_MODEL)
        if not model_dir.is_dir():
            blockers.append(f"CosyVoice2 model_dir missing: {model_dir}")
        elif not (model_dir / "cosyvoice2.yaml").is_file():
            blockers.append(f"cosyvoice2.yaml not found in {model_dir}")
        return blockers

    @staticmethod
    def _patch_torchaudio_load() -> None:
        """Torchaudio 2.13+ wants torchcodec+ffmpeg; use soundfile for prompt wav loads."""
        import soundfile as sf
        import torch
        import torchaudio

        def _load(path, *args, **kwargs):
            data, sr = sf.read(path, dtype="float32", always_2d=False)
            if getattr(data, "ndim", 1) > 1:
                data = data[:, 0]
            return torch.from_numpy(data).unsqueeze(0), int(sr)

        torchaudio.load = _load  # type: ignore[method-assign]

    def _init_cosyvoice(self) -> None:
        blockers = self._probe_cosyvoice_blockers()
        if blockers:
            self.blockers.extend(blockers)
            return
        tts_cfg = (self.cfg.get("tts") or {}).get("cosyvoice") or {}
        model_dir = str(Path(tts_cfg.get("model_dir") or DEFAULT_COSYVOICE_MODEL))
        matcha = str(COSYVOICE_REPO / "third_party" / "Matcha-TTS")
        repo = str(COSYVOICE_REPO)
        for p in (matcha, repo):
            if p not in sys.path:
                sys.path.insert(0, p)
        try:
            self._patch_torchaudio_load()
            _patch_cosyvoice_device()
            from cosyvoice.cli.cosyvoice import AutoModel  # type: ignore

            self._cosyvoice = AutoModel(model_dir=model_dir)
            self._cosyvoice_sr = int(getattr(self._cosyvoice, "sample_rate", 24000))
            spks = list(self._cosyvoice.list_available_spks())
            want = str(tts_cfg.get("speaker") or "default")
            self._cosyvoice_speaker = want if want in spks else (spks[0] if spks else None)
            prompt = tts_cfg.get("prompt_wav") or str(COSYVOICE_REPO / "asset" / "cross_lingual_prompt.wav")
            self._cosyvoice_prompt_wav = prompt if Path(prompt).is_file() else None
            if not self._cosyvoice_speaker and not self._cosyvoice_prompt_wav:
                self.blockers.append("CosyVoice2: no SFT speaker and no prompt_wav")
                self._cosyvoice = None
                return
            self._tts_active = "cosyvoice2"
            logger.info(
                "CosyVoice2 ready mode=%s speaker=%s prompt=%s sr=%s",
                "sft" if self._cosyvoice_speaker else "cross_lingual",
                self._cosyvoice_speaker,
                self._cosyvoice_prompt_wav,
                self._cosyvoice_sr,
            )
        except Exception as exc:
            self.blockers.append(f"CosyVoice2 init failed: {exc}")
            logger.exception("CosyVoice2 init failed")

    def _init_kokoro(self) -> None:
        tts_cfg = (self.cfg.get("tts") or {})
        kokoro_dir = (tts_cfg.get("kokoro") or {}).get("model_dir") or ""
        model = Path.home() / ".cache" / "kokoro" / "kokoro-v1.0.onnx"
        voices = Path.home() / ".cache" / "kokoro" / "voices-v1.0.bin"
        if kokoro_dir:
            model = Path(kokoro_dir) / "kokoro-v1.0.onnx"
            voices = Path(kokoro_dir) / "voices-v1.0.bin"
        try:
            from kokoro_onnx import Kokoro  # type: ignore

            if model.is_file() and voices.is_file():
                self._kokoro = Kokoro(str(model), str(voices))
                if self._tts_active == "unavailable":
                    self._tts_active = "kokoro"
                    self.blockers.append(
                        "CosyVoice2 unavailable — Kokoro fallback active (English-only G2P; not §9.3 primary)"
                    )
        except Exception as exc:
            logger.warning("kokoro init failed: %s", exc)

    def _init_asr(self) -> None:
        asr_cfg = self.cfg.get("asr") or {}
        prefer = str(asr_cfg.get("model") or "SenseVoiceSmall")
        device = str(asr_cfg.get("device") or "mps")
        if prefer.lower().startswith("sensevoice"):
            snap = sensevoice_snapshot_dir()
            pt = sensevoice_model_pt_path()
            if pt is not None:
                logger.info(
                    "SenseVoice cache: %s (%s, %.1f%%)",
                    pt,
                    pt.name,
                    (pt.stat().st_size / _SENSEVOICE_MODEL_BYTES) * 100,
                )
            for dev in (device, "cpu"):
                try:
                    from funasr import AutoModel  # type: ignore

                    kwargs: dict[str, Any] = {
                        "model": SENSEVOICE_HUB_ID,
                        "device": dev,
                        "disable_update": True,
                        "check_latest": False,
                        "hub": "ms",
                    }
                    if snap and (snap / "model.pt").is_file():
                        kwargs["model_path"] = str(snap)
                    self._sensevoice = AutoModel(**kwargs)
                    self._asr_name = "sensevoice"
                    logger.info("SenseVoice-Small ready device=%s cache=%s", dev, snap)
                    break
                except Exception as exc:
                    self.blockers.append(f"SenseVoice init failed ({dev}): {exc}")
        try:
            from faster_whisper import WhisperModel  # type: ignore

            self._whisper = WhisperModel("small", device="cpu", compute_type="int8")
            if self._asr_name != "sensevoice":
                self._asr_name = "faster_whisper"
                if prefer.lower().startswith("sensevoice"):
                    self.blockers.append(
                        "ASR fallback faster_whisper: emotion/event=null on fallback path"
                    )
        except Exception as exc:
            if self._asr_name != "sensevoice":
                self.blockers.append(f"faster_whisper init failed: {exc}")

    def health(self) -> dict:
        decision = (self._warmup_stats or {}).get("tts_decision", "primary")
        return {
            "asr": self._asr_name if self._asr_name != "unavailable" else "unloaded",
            "tts": self._tts_active if self._tts_active != "unavailable" else "unloaded",
            "tts_engine": self._tts_primary,
            "tts_active": self._tts_active,
            "tts_route_policy": decision,
            "blockers": list(self.blockers),
            "warmup": self._warmup_stats,
        }

    def resolve_tts_engine(self, text: str, *, engine: str | None = None) -> tuple[str, TtsRoute]:
        """Pick CosyVoice2 vs Kokoro for one sentence (auto honors warmup tts_decision)."""
        want = (engine or "auto").lower()
        if want in ("kokoro",):
            return "kokoro", TtsRoute(engine="kokoro", reason="explicit")
        if want in ("cosyvoice2", "cosyvoice"):
            return "cosyvoice2", TtsRoute(engine="cosyvoice2", reason="explicit")

        decision = (self._warmup_stats or {}).get("tts_decision", "primary")
        locale = classify_tts_locale(text)
        if (
            decision == "code_switch_specialist"
            and is_pure_english_sentence(text)
            and self._kokoro is not None
        ):
            return "kokoro", TtsRoute(
                engine="kokoro",
                reason=f"code_switch_specialist:{locale}",
            )
        if decision == "code_switch_specialist":
            return "cosyvoice2", TtsRoute(
                engine="cosyvoice2",
                reason=f"code_switch_specialist:{locale}",
            )
        return "cosyvoice2", TtsRoute(engine="cosyvoice2", reason="primary")

    def transcribe(self, pcm: bytes, *, sample_rate: int = 16000, duration_ms: int = 0) -> AsrResult:
        if len(pcm) < sample_rate // 5:
            return AsrResult(
                text="",
                lang="mixed",
                emotion=None,
                event=None,
                duration_ms=duration_ms,
                engine=self._asr_name,
            )
        if self._sensevoice is not None:
            wav = _pcm16_to_wav(pcm, sample_rate)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav)
                tmp.flush()
                try:
                    res = self._sensevoice.generate(input=tmp.name, cache={}, language="auto", use_itn=True)
                    raw = ""
                    if res and isinstance(res, list) and res[0].get("text"):
                        raw = str(res[0]["text"])
                    text, lang, emotion, event = _parse_sensevoice_output(raw)
                    return AsrResult(
                        text=text,
                        lang=lang,
                        emotion=emotion,
                        event=event,
                        duration_ms=duration_ms,
                        engine="sensevoice",
                    )
                finally:
                    Path(tmp.name).unlink(missing_ok=True)
        if self._whisper is not None:
            wav = _pcm16_to_wav(pcm, sample_rate)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                tmp.write(wav)
                tmp.flush()
                segments, info = self._whisper.transcribe(tmp.name, beam_size=1, vad_filter=True)
                text = "".join(s.text for s in segments).strip()
                lang = getattr(info, "language", None) or "mixed"
                if lang.startswith("zh"):
                    lang = "zh"
                elif lang.startswith("en"):
                    lang = "en"
                else:
                    lang = "mixed"
                return AsrResult(
                    text=text,
                    lang=lang,
                    emotion=None,
                    event=None,
                    duration_ms=duration_ms,
                    engine="faster_whisper",
                )
        return AsrResult(
            text="",
            lang="mixed",
            emotion=None,
            event=None,
            duration_ms=duration_ms,
            engine="unloaded",
        )

    @property
    def last_tts_synthesis(self) -> dict[str, Any] | None:
        return self._last_tts_synthesis.as_dict() if self._last_tts_synthesis else None

    def _record_tts_synthesis(
        self,
        *,
        text: str,
        route: TtsRoute,
        actual_engine: str,
        t0: float,
        first_ms: float | None,
        pcm_bytes: int,
        fallback_from: str | None = None,
        fallback_reason: str | None = None,
    ) -> TtsSynthesisStats:
        elapsed = time.perf_counter() - t0
        audio_sec = pcm_bytes / (2 * 24000) if pcm_bytes else 0.0
        rtf = (elapsed / audio_sec) if audio_sec > 0 else None
        device = None
        if actual_engine == "cosyvoice2":
            snap = self._cosyvoice_device_snapshot()
            device = str(snap.get("llm_param_device") or snap.get("model_device") or "unknown")
        stats = TtsSynthesisStats(
            engine=actual_engine,
            locale=classify_tts_locale(text),
            route=route.reason or "",
            device=device,
            first_packet_ms=round(first_ms or 0.0, 1) if first_ms is not None else None,
            elapsed_sec=round(elapsed, 3),
            audio_sec=round(audio_sec, 3),
            rtf=round(rtf, 3) if rtf is not None else None,
            fallback_from=fallback_from,
            fallback_reason=fallback_reason,
        )
        self._last_tts_synthesis = stats
        logger.info(
            "TTS synthesis text=%r engine=%s locale=%s route=%s device=%s rtf=%s first_ms=%s "
            "elapsed=%ss audio=%ss fallback=%s",
            (text or "")[:80],
            stats.engine,
            stats.locale,
            stats.route,
            stats.device,
            stats.rtf,
            stats.first_packet_ms,
            stats.elapsed_sec,
            stats.audio_sec,
            stats.fallback_from or "-",
        )
        return stats

    def tts_pcm_chunks(self, text: str, *, engine: str | None = None) -> Iterator[bytes]:
        chosen, route = self.resolve_tts_engine(text, engine=engine)
        t0 = time.perf_counter()
        first_ms: float | None = None
        pcm_bytes = 0
        actual_engine = chosen
        fallback_from: str | None = None
        fallback_reason: str | None = None

        def _emit(chunks: Iterator[bytes]) -> Iterator[bytes]:
            nonlocal first_ms, pcm_bytes
            for chunk in chunks:
                if first_ms is None:
                    first_ms = (time.perf_counter() - t0) * 1000.0
                pcm_bytes += len(chunk)
                yield chunk

        try:
            if chosen == "cosyvoice2":
                try:
                    yield from _emit(self._cosyvoice_chunks(text))
                    return
                except Exception as exc:
                    fallback_from = "cosyvoice2"
                    fallback_reason = str(exc)
                    actual_engine = "kokoro"
                    route = TtsRoute(engine="kokoro", fallback_from="cosyvoice2", reason=str(exc))
                    logger.error("CosyVoice2 TTS failed, Kokoro fallback: %s", exc)
            elif chosen == "kokoro":
                try:
                    logger.info("TTS route: %s", route)
                    yield from _emit(self._kokoro_chunks(text))
                    return
                except Exception as exc:
                    logger.error("Kokoro TTS failed, CosyVoice2 fallback: %s", exc)
                    if self._cosyvoice is not None:
                        fallback_from = "kokoro"
                        fallback_reason = str(exc)
                        actual_engine = "cosyvoice2"
                        yield from _emit(self._cosyvoice_chunks(text))
                        return
                    raise TtsUnavailableError(
                        "Kokoro failed and CosyVoice2 unavailable",
                        blockers=self.blockers + [str(exc)],
                    ) from exc
            if self._kokoro is not None:
                logger.warning("TTS route fallback: %s", route)
                actual_engine = "kokoro"
                yield from _emit(self._kokoro_chunks(text))
                return
            raise TtsUnavailableError(
                "no TTS engine available",
                blockers=self.blockers + [route.reason or "CosyVoice2 and Kokoro both unavailable"],
            )
        finally:
            self._record_tts_synthesis(
                text=text,
                route=route,
                actual_engine=actual_engine,
                t0=t0,
                first_ms=first_ms,
                pcm_bytes=pcm_bytes,
                fallback_from=fallback_from,
                fallback_reason=fallback_reason,
            )

    def _cosyvoice_chunks(self, text: str) -> Iterator[bytes]:
        if not self._cosyvoice:
            raise TtsUnavailableError("CosyVoice2 not loaded", blockers=self.blockers)
        if self._cosyvoice_speaker:
            stream = self._cosyvoice.inference_sft(
                text, self._cosyvoice_speaker, stream=True, text_frontend=True
            )
        elif self._cosyvoice_prompt_wav:
            stream = self._cosyvoice.inference_cross_lingual(
                text, self._cosyvoice_prompt_wav, stream=True, text_frontend=True
            )
        else:
            raise TtsUnavailableError("CosyVoice2: no inference route", blockers=self.blockers)
        for model_output in stream:
            pcm, sr = _float_tensor_to_pcm16(model_output["tts_speech"], self._cosyvoice_sr)
            if sr != 24000:
                pcm = _resample_pcm16(pcm, sr, 24000)
            for i in range(0, len(pcm), 4800):
                yield pcm[i : i + 4800]

    def _kokoro_chunks(self, text: str) -> Iterator[bytes]:
        if not self._kokoro:
            raise TtsUnavailableError("Kokoro not loaded", blockers=self.blockers)
        voice = ((self.cfg.get("tts") or {}).get("kokoro") or {}).get("voice") or "af_heart"
        samples, sr = self._kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
        pcm, out_sr = _float_tensor_to_pcm16(samples, int(sr))
        if out_sr != 24000:
            pcm = _resample_pcm16(pcm, out_sr, 24000)
        for i in range(0, len(pcm), 4800):
            yield pcm[i : i + 4800]

    def _cosyvoice_device_snapshot(self) -> dict:
        """Report where CosyVoice weights actually landed (cuda/mps/cpu)."""
        tts_cfg = (self.cfg.get("tts") or {}).get("cosyvoice") or {}
        snap: dict[str, Any] = {
            "configured_device": tts_cfg.get("device"),
            "patch_active": _COSYVOICE_DEVICE_PATCHED,
            "resolved_device": str(_resolve_cosyvoice_device()) if _COSYVOICE_DEVICE_PATCHED else None,
            "torch_cuda_available": False,
            "torch_mps_available": False,
            "mps_fallback_env": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"),
        }
        try:
            import torch

            snap["torch_cuda_available"] = bool(torch.cuda.is_available())
            snap["torch_mps_available"] = bool(torch.backends.mps.is_available())
        except Exception as exc:
            snap["torch_probe_error"] = str(exc)
        if not self._cosyvoice:
            snap["model_device"] = "not_loaded"
            return snap
        model = getattr(self._cosyvoice, "model", None)
        if model is not None:
            snap["model_device"] = str(getattr(model, "device", "unknown"))
            for name in ("llm", "flow", "hift"):
                sub = getattr(model, name, None)
                if sub is not None:
                    try:
                        snap[f"{name}_param_device"] = str(next(sub.parameters()).device)
                    except StopIteration:
                        pass
        frontend = getattr(self._cosyvoice, "frontend", None)
        if frontend is not None:
            snap["frontend_device"] = str(getattr(frontend, "device", "unknown"))
        return snap

    def _warmup_tts_once(self, utterance: str) -> dict:
        t0 = time.perf_counter()
        first_ms: float | None = None
        pcm_bytes = 0
        try:
            for chunk in self.tts_pcm_chunks(utterance, engine="cosyvoice2"):
                if first_ms is None:
                    first_ms = (time.perf_counter() - t0) * 1000.0
                pcm_bytes += len(chunk)
        except Exception as exc:
            return {"error": str(exc)}
        elapsed = time.perf_counter() - t0
        audio_sec = pcm_bytes / (2 * 24000) if pcm_bytes else 0.0
        rtf = (elapsed / audio_sec) if audio_sec > 0 else None
        return {
            "warm_first_packet_ms": round(first_ms or 0.0, 1),
            "warm_rtf": round(rtf, 3) if rtf is not None else None,
            "audio_sec": round(audio_sec, 3),
            "elapsed_sec": round(elapsed, 3),
        }

    def warmup_tts(self, text: str | None = None, *, runs: int = WARMUP_RUNS) -> dict:
        """Boot-time CosyVoice preload — `runs` iterations, median warm RTF (spec §9.1)."""
        utterance = text or WARMUP_TEXT
        if self._tts_active != "cosyvoice2":
            return {"skipped": True, "reason": "cosyvoice2 not active"}
        run_stats: list[dict] = []
        errors: list[str] = []
        for _ in range(max(1, runs)):
            one = self._warmup_tts_once(utterance)
            if one.get("error"):
                errors.append(str(one["error"]))
            else:
                run_stats.append(one)
        devices = self._cosyvoice_device_snapshot()
        if not run_stats:
            return {"error": errors[-1] if errors else "no successful warmup runs", "devices": devices}
        rtfs = [r["warm_rtf"] for r in run_stats if r.get("warm_rtf") is not None]
        firsts = [r["warm_first_packet_ms"] for r in run_stats]
        median_rtf = statistics.median(rtfs) if rtfs else None
        median_first = statistics.median(firsts) if firsts else 0.0
        last = run_stats[-1]
        stats = {
            "text": utterance,
            "warm_runs": len(run_stats),
            "warm_rtf_median": round(median_rtf, 3) if median_rtf is not None else None,
            "warm_first_packet_ms_median": round(median_first, 1),
            "warm_rtf": round(median_rtf, 3) if median_rtf is not None else None,
            "warm_first_packet_ms": round(median_first, 1),
            "audio_sec": last.get("audio_sec"),
            "runs": run_stats,
            "devices": devices,
            "mps_primary_eligible": median_rtf is not None and median_rtf <= 2.5,
            "ts": time.time(),
        }
        if stats["mps_primary_eligible"]:
            stats["tts_decision"] = "primary"
        else:
            stats["tts_decision"] = "code_switch_specialist"
            self.blockers.append(
                f"TTS routing: code_switch_specialist (median RTF {stats['warm_rtf_median']}) — "
                "en→Kokoro, zh/mixed→CosyVoice2"
            )
        on_mps = devices.get("llm_param_device", "").startswith("mps")
        logger.info(
            "voice TTS warmup x%d: median_rtf=%s first_ms=%s devices model=%s llm=%s flow=%s on_mps=%s eligible=%s",
            len(run_stats),
            stats["warm_rtf_median"],
            stats["warm_first_packet_ms_median"],
            devices.get("model_device"),
            devices.get("llm_param_device"),
            devices.get("flow_param_device"),
            on_mps,
            stats["mps_primary_eligible"],
        )
        self._warmup_stats = stats
        return stats


def frame_tts(chunk: bytes) -> bytes:
    return bytes([CH_TTS]) + chunk
