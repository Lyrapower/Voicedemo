"""Descriptive model/capability profiles.

These profiles are metadata for Grid's capability surface. They are NOT routing rules.
Harness must never choose a model merely because a task type matches a profile.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ModelProfile:
    node_id: str
    role: str
    strengths: tuple[str, ...]
    evidence_policy: str
    may_self_verify: bool = False
    memory_mode: str = "candidate_only"
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


PROFILES: dict[str, ModelProfile] = {
    "grid_local": ModelProfile(
        node_id="grid_local",
        role="cognition_owner",
        strengths=("intent_interpretation", "planning", "resource_choice", "self_correction", "cognitive_stop"),
        evidence_policy="May choose and synthesize; hard real-world claims still require receipts/verifier.",
        may_self_verify=False,
        memory_mode="owner",
        notes="Native operation must not be overwritten by external planner/loop.",
    ),
    "glm_5_2": ModelProfile(
        node_id="glm_5_2",
        role="open_world_cognition_resource",
        strengths=("question_premise", "research_taste", "open_world_judgment", "strategy", "evidence_interpretation"),
        evidence_policy="High-trust cognition resource; cannot promote unreceipted execution to VERIFIED.",
        may_self_verify=False,
        memory_mode="cloud_scoped",
        notes="Available to Grid; not a mandatory default route.",
    ),
    "deepseek_v4_pro": ModelProfile(
        node_id="deepseek_v4_pro",
        role="scout_quant_candidate",
        strengths=("quant_research", "scenario_search", "candidate_generation", "tactical_analysis"),
        evidence_policy="Candidate only for execution/factual completion claims until independently evidenced.",
        may_self_verify=False,
        memory_mode="cloud_scoped",
    ),
    "kimi_k3": ModelProfile(
        node_id="kimi_k3",
        role="long_context_multimodal_candidate",
        strengths=("long_context", "document_synthesis", "native_multimodal"),
        evidence_policy="Candidate only for execution/factual completion claims until independently evidenced.",
        may_self_verify=False,
        memory_mode="cloud_scoped",
    ),
    "minimax_m3": ModelProfile(
        node_id="minimax_m3",
        role="stateless_multimodal_bypass",
        strengths=("image_read", "audio_asr", "audio_tts", "audio_analyze", "video_analyze"),
        evidence_policy="CANDIDATE_MULTIMODAL only unless downstream deterministic verification proves a fact.",
        may_self_verify=False,
        memory_mode="stateless",
        notes="Kimi native multimodal should not be forced through MiniMax.",
    ),
    "qwen_coder_local": ModelProfile(
        node_id="qwen_coder_local",
        role="local_execution_worker",
        strengths=("code_generation", "local_file_tasks", "bounded_execution_support"),
        evidence_policy="Execution becomes fact only from real tool/process receipt + verifier.",
        may_self_verify=False,
        memory_mode="local_scoped",
    ),
    "claude_code": ModelProfile(
        node_id="claude_code",
        role="bounded_engineering_executor",
        strengths=("repo_edit", "tests", "build", "deployment_scaffolding"),
        evidence_policy="Must emit execution receipts; deny-by-default tools/paths; hard postcondition verification required.",
        may_self_verify=False,
        memory_mode="local_scoped",
    ),
}


def list_model_profiles() -> list[dict]:
    return [PROFILES[k].to_dict() for k in sorted(PROFILES)]
