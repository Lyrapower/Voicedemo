from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib


@dataclass(frozen=True)
class CoreConfig:
    db_path: str
    gateway_base: str
    gateway_timeout_seconds: float
    poll_interval_seconds: float
    max_retries: int
    max_concurrency: int


@dataclass(frozen=True)
class ModelConfig:
    local_route: str
    fast_route: str
    deep_route: str
    full_route: str
    research_route: str


@dataclass(frozen=True)
class CCConfig:
    enabled: bool
    binary: str
    work_root: str
    timeout_seconds: int


@dataclass(frozen=True)
class HarnessConfig:
    host: str
    port: int


@dataclass(frozen=True)
class Audio8VoiceConfig:
    enabled: bool
    host: str
    port: int
    model: str
    default_voice_en: str
    default_voice_zh: str
    timeout_seconds: float


@dataclass(frozen=True)
class VoiceConfig:
    provider: str
    fallback_provider: str
    fallback_enabled: bool
    audio8: Audio8VoiceConfig


@dataclass(frozen=True)
class RelayConfig:
    enabled: bool
    url: str
    device_id: str
    token_env: str
    reconnect_seconds: int


@dataclass(frozen=True)
class PolicyConfig:
    cloud_default: bool
    auto_resume_interrupted: bool
    allow_deploy: bool


@dataclass(frozen=True)
class MemoryDomainConfig:
    kind: str
    base_url: str
    stable_core_path: str
    active_state_path: str
    recall_path: str
    write_path: str
    auth_env: str
    timeout_seconds: float
    required: bool
    write_mode: str


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool
    subject_id: str
    context_owner: str
    strict_domain_isolation: bool
    emit_context_receipts: bool
    local: MemoryDomainConfig
    cloud: MemoryDomainConfig


@dataclass(frozen=True)
class ContextProfileConfig:
    memory_domain: str
    max_context_tokens: int
    reserve_output_tokens: int
    stable_core_tokens: int
    active_state_tokens: int
    recent_turns_tokens: int
    recall_tokens: int
    recall_top_k: int


@dataclass(frozen=True)
class ContextConfig:
    recent_turns_cap: int
    estimator: str
    framing_reserve_tokens: int
    local: ContextProfileConfig
    cc: ContextProfileConfig
    fast: ContextProfileConfig
    deep: ContextProfileConfig
    full: ContextProfileConfig
    research: ContextProfileConfig

    def profile(self, worker: str) -> ContextProfileConfig:
        if worker == "local":
            return self.local
        if worker == "cc":
            return self.cc
        if worker == "fast":
            return self.fast
        if worker == "deep":
            return self.deep
        if worker == "full":
            return self.full
        if worker == "research":
            return self.research
        raise ValueError(f"unknown worker context profile: {worker}")


@dataclass(frozen=True)
class Config:
    core: CoreConfig
    models: ModelConfig
    cc: CCConfig
    harness: HarnessConfig
    voice: VoiceConfig
    relay: RelayConfig
    policy: PolicyConfig
    memory: MemoryConfig
    context: ContextConfig


def _memory_domain(data: dict) -> MemoryDomainConfig:
    return MemoryDomainConfig(**data)


def _context_profile(data: dict) -> ContextProfileConfig:
    return ContextProfileConfig(**data)


def load_config(path: str = "config.toml") -> Config:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    mem = data["memory"]
    ctx = data["context"]

    if mem["context_owner"] not in {"shadow", "harness", "gateway"}:
        raise ValueError("memory.context_owner must be shadow|harness|gateway")

    local = _memory_domain(mem["local"])
    cloud = _memory_domain(mem["cloud"])

    if mem["strict_domain_isolation"]:
        if not local.base_url or not cloud.base_url:
            raise ValueError("strict domain isolation requires explicit local/cloud memory domains")
        local_paths=(local.stable_core_path,local.active_state_path,local.recall_path)
        cloud_paths=(cloud.stable_core_path,cloud.active_state_path,cloud.recall_path)
        if local.base_url==cloud.base_url and local_paths==cloud_paths:
            raise ValueError("strict domain isolation forbids identical local/cloud memory endpoints")

    for domain in (local, cloud):
        if domain.kind != "http_json":
            raise ValueError("V1.2 currently supports memory domain kind=http_json")
        if domain.write_mode not in {"gateway_owned", "external", "none"}:
            raise ValueError("memory domain write_mode must be gateway_owned|external|none")
        if domain.write_mode == "external" and not domain.write_path:
            raise ValueError("write_mode=external requires write_path")

    if ctx["estimator"] != "utf8_bytes_upper_bound":
        raise ValueError("V1.2 currently supports estimator=utf8_bytes_upper_bound")

    for worker in ("local", "cc", "fast", "deep", "full", "research"):
        p = _context_profile(ctx[worker])
        available = p.max_context_tokens - p.reserve_output_tokens - ctx["framing_reserve_tokens"]
        if available <= 0:
            raise ValueError(f"{worker}: reserve_output_tokens leaves no input context")
        if p.stable_core_tokens + p.active_state_tokens >= available:
            raise ValueError(
                f"{worker}: protected STABLE_CORE + ACTIVE_STATE budgets consume the entire input window"
            )
        if p.memory_domain not in {"local", "cloud"}:
            raise ValueError(f"{worker}: memory_domain must be local|cloud")

    harness_raw = data.get("harness") or data.get("api")
    if not harness_raw:
        raise ValueError("config.toml requires [harness] (or legacy [api])")

    voice_raw = data.get("voice") or {}
    audio8_raw = voice_raw.get("audio8") or {}
    tts_port = int(audio8_raw.get("port", 8631))
    harness_port = int(harness_raw["port"])
    if tts_port == harness_port:
        raise ValueError(
            f"voice.audio8.port ({tts_port}) must differ from harness.port ({harness_port})"
        )
    if tts_port == 8630:
        raise ValueError("voice.audio8.port must not be 8630 (reserved for harness)")

    audio8 = Audio8VoiceConfig(
        enabled=bool(audio8_raw.get("enabled", False)),
        host=str(audio8_raw.get("host", "127.0.0.1")),
        port=tts_port,
        model=str(audio8_raw.get("model", "Audio8/Audio8-TTS-Preview-0.6B-ONNX-INT4")),
        default_voice_en=str(audio8_raw.get("default_voice_en", "grid_en")),
        default_voice_zh=str(audio8_raw.get("default_voice_zh", "grid_zh")),
        timeout_seconds=float(audio8_raw.get("timeout_seconds", 120)),
    )

    return Config(
        core=CoreConfig(**data["core"]),
        models=ModelConfig(**data["models"]),
        cc=CCConfig(**data["cc"]),
        harness=HarnessConfig(**harness_raw),
        voice=VoiceConfig(
            provider=str(voice_raw.get("provider", "audio8_onnx")),
            fallback_provider=str(voice_raw.get("fallback_provider", "openai_realtime")),
            fallback_enabled=bool(voice_raw.get("fallback_enabled", False)),
            audio8=audio8,
        ),
        relay=RelayConfig(**data["relay"]),
        policy=PolicyConfig(**data["policy"]),
        memory=MemoryConfig(
            enabled=mem["enabled"],
            subject_id=mem["subject_id"],
            context_owner=mem["context_owner"],
            strict_domain_isolation=mem["strict_domain_isolation"],
            emit_context_receipts=mem["emit_context_receipts"],
            local=local,
            cloud=cloud,
        ),
        context=ContextConfig(
            recent_turns_cap=ctx["recent_turns_cap"],
            estimator=ctx["estimator"],
            framing_reserve_tokens=ctx["framing_reserve_tokens"],
            local=_context_profile(ctx["local"]),
            cc=_context_profile(ctx["cc"]),
            fast=_context_profile(ctx["fast"]),
            deep=_context_profile(ctx["deep"]),
            full=_context_profile(ctx["full"]),
            research=_context_profile(ctx["research"]),
        ),
    )


def gateway_headers() -> dict[str, str]:
    token = os.getenv("GRID_GATEWAY_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}
