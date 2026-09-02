"""Audio8 ONNX TTS adapter — harness TTS leg on :8631."""
from __future__ import annotations

import httpx

from .config import Audio8VoiceConfig, Config


class VoiceTtsAdapter:
    """Synthesize WAV via Audio8 sidecar; no memory or worker routing here."""

    def __init__(self, cfg: Audio8VoiceConfig):
        self.cfg = cfg
        self._client = httpx.AsyncClient(
            base_url=f"http://{cfg.host}:{cfg.port}",
            timeout=cfg.timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    def voice_for_lang(self, lang: str) -> str:
        if lang.lower().startswith("zh"):
            return self.cfg.default_voice_zh
        return self.cfg.default_voice_en

    async def synthesize_wav(self, text: str, voice: str | None = None) -> bytes:
        if not self.cfg.enabled:
            raise RuntimeError("voice.audio8.enabled is false")
        voice_name = voice or self.cfg.default_voice_en
        r = await self._client.post(
            "/v1/audio/speech",
            json={
                "model": "arktts",
                "input": text,
                "voice": voice_name,
                "response_format": "wav",
            },
        )
        r.raise_for_status()
        return r.content


def voice_tts_adapter(cfg: Config) -> VoiceTtsAdapter:
    return VoiceTtsAdapter(cfg.voice.audio8)
