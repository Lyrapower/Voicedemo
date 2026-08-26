"""Capability surface for Grid.

This module exposes what exists. It deliberately contains no task-type -> model routing.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from app.harness.model_profiles import list_model_profiles


@dataclass(frozen=True)
class Capability:
    capability_id: str
    provider: str
    kind: str
    permission: str
    status: str = "declared"
    produces: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


STATIC_CAPABILITIES = (
    Capability("crypto.rwa.scan_public", "local_scanner", "tool", "read_only", produces=("scan_receipt", "evidence_candidates")),
    Capability("crypto.rwa.generate_pack", "crypto_rwa_generator", "tool", "local_write", produces=("research_artifacts",)),
    Capability("crypto.proof.compile", "compiled_memory", "tool", "local_write", produces=("compiled_workspace",)),
    Capability("trading.paper.signal_daily", "aether_paper", "tool", "paper_only", produces=("paper_signals",)),
    Capability("trading.paper.cli", "aether_paper", "tool", "paper_only", produces=("paper_receipts",)),
    Capability("aether.crypto.snapshot", "aether_crypto", "tool", "read_only", produces=("market_state",)),
    Capability("image.read", "minimax_m3", "model_tool", "media_scoped", produces=("candidate_multimodal",)),
    Capability("audio.asr", "minimax_m3", "model_tool", "media_scoped", produces=("candidate_transcript",)),
    Capability("audio.tts", "minimax_m3", "model_tool", "media_scoped", produces=("audio_artifact",)),
    Capability("video.analyze", "minimax_m3", "model_tool", "media_scoped", produces=("candidate_multimodal",)),
    Capability("voice.realtime", "personaplex_local", "voice_io", "loopback", produces=("audio_stream",), notes="127.0.0.1:8631; Harness remains on 8630."),
)


def _legacy_task_capabilities() -> list[dict[str, Any]]:
    """Read legacy Jarvis task specs as capability metadata only.

    Any import failure is truthful: the bundle is a merge package and may not contain the
    full host repository dependencies.
    """
    try:
        from app.jarvis.task_registry import list_tasks
        tasks = list_tasks()
    except Exception as exc:  # truthful host-repo dependency boundary
        return [{"status": "unavailable", "source": "legacy_task_registry", "error": str(exc)}]
    out = []
    for task in tasks:
        out.append({
            "capability_id": f"legacy.{task.get('task_id', '')}",
            "provider": "jarvis_task_registry",
            "kind": "legacy_tool",
            "permission": task.get("permission", "read_only"),
            "status": "available" if task.get("enabled") else "disabled",
            "schedule": task.get("schedule", "manual"),
            "handler": task.get("handler", ""),
            "note": "Capability metadata only; not a cognitive routing instruction.",
        })
    return out


def capability_surface() -> dict[str, Any]:
    return {
        "routing_policy": "GRID_CHOOSES",
        "registry_role": "MAP_NOT_DRIVER",
        "capabilities": [c.to_dict() for c in STATIC_CAPABILITIES] + _legacy_task_capabilities(),
        "model_profiles": list_model_profiles(),
        "hard_rules": [
            "no silent resource substitution",
            "candidate output cannot self-promote to VERIFIED",
            "real execution requires receipt",
            "Verifier returns facts, not next-step cognition",
        ],
    }
