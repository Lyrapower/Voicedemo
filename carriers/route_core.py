"""Shared /route execution — plain user prompt only (no anchor/RAG injection)."""

from __future__ import annotations

import logging
import time
import uuid
import json
from typing import Any, Dict, List, Optional

from compiler import SemanticMapper
from models import get_loader

logger = logging.getLogger(__name__)


def build_carrier_final_prompt(
    *,
    invoked_carrier: str,
    user_prompt: str,
    anchor_loader: Any | None = None,
    memory_service: Any | None = None,
) -> tuple[str, List[Dict]]:
    return user_prompt, []


def compile_with_carrier_prompt(
    prompt: str,
    *,
    explicit_carrier: Optional[str] = None,
    mapper: SemanticMapper | None = None,
    anchor_loader: Any | None = None,
    memory_service: Any | None = None,
) -> tuple[Any, str, Optional[str]]:
    mapper = mapper or SemanticMapper()
    compiled = mapper.compile_intent(prompt)
    user_prompt = compiled.cleaned_prompt or prompt
    return compiled, user_prompt, None


def execute_route(
    *,
    prompt: str,
    explicit_layer: Optional[str] = None,
    explicit_carrier: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    session_id: Optional[str] = None,
    mapper: SemanticMapper | None = None,
    loader: Any | None = None,
    anchor_loader: Any | None = None,
    memory_service: Any | None = None,
) -> Dict[str, Any]:
    del explicit_carrier, anchor_loader, memory_service

    mapper = mapper or SemanticMapper()
    loader = loader or get_loader()

    audit_id = str(uuid.uuid4())
    timestamp = time.time()

    compiled = mapper.compile_intent(prompt)
    target_layer = explicit_layer or compiled.target_layer
    user_prompt = compiled.cleaned_prompt or prompt

    from models.aster_config import direct_1234_allowed
    from models.gateway_client import gateway_compile, gateway_dialogue_envelope, dialogue_display_text

    if not direct_1234_allowed():
        compile_mode = (
            explicit_layer == "compile_layer"
            or "compile" in (user_prompt or "").lower()[:80]
            or "json_ast" in (user_prompt or "").lower()
        )
        if compile_mode:
            gw = gateway_compile(user_prompt)
            if gw is None:
                return {
                    "error": "gateway :8501 /compile unreachable",
                    "audit_id": audit_id,
                    "timestamp": timestamp,
                    "compiled_intent": compiled.to_dict(),
                }
            verdict = gw.get("computed_verdict") or gw.get("verdict")
            draft_only = bool(gw.get("draft_only", True))
            if verdict == "PASS":
                draft = gw.get("draft_echo") or gw.get("human_echo") or json.dumps(
                    gw.get("draft_ast") or gw.get("ast") or {}, ensure_ascii=False,
                )
                response = f"[DRAFT — not presence evidence] {draft}" if draft_only else draft
            elif verdict == "NULL":
                null = gw.get("null") or {}
                response = f"NULL — {null.get('reason', 'compile returned NULL')}"
            else:
                response = gw.get("reason") or "compile FAIL"
            generation_result = {
                "response": response,
                "eval_count": 0,
                "total_duration_ns": 0,
                "carrier_capable": False,
                "echo_mode": False,
                "backend": "gateway:compile",
                "verdict": verdict,
                "computed_verdict": verdict,
                "draft_only": draft_only,
            }
        else:
            env = gateway_dialogue_envelope(user_prompt, user_id="8787-route")
            text = dialogue_display_text(env)
            if text is None and env is None:
                return {
                    "error": "gateway :8501 /gateway unreachable or blocked",
                    "audit_id": audit_id,
                    "timestamp": timestamp,
                    "compiled_intent": compiled.to_dict(),
                }
            generation_result = {
                "response": text,
                "eval_count": 0,
                "total_duration_ns": 0,
                "carrier_capable": False,
                "echo_mode": True,
                "backend": "gateway:dialogue",
                "computed_verdict": (env or {}).get("computed_verdict"),
                "draft_only": (env or {}).get("draft_only", True),
                "blocked": (env or {}).get("blocked", False),
            }
    else:
        generation_result = loader.generate(
            target_layer,
            user_prompt,
            temperature_override=temperature,
            max_tokens_override=max_tokens,
            carrier=None,
            system_override="",
        )

    if "error" in generation_result:
        return {
            "error": generation_result["error"],
            "audit_id": audit_id,
            "timestamp": timestamp,
            "compiled_intent": compiled.to_dict(),
        }

    return {
        "audit_id": audit_id,
        "timestamp": timestamp,
        "invoked_carrier": None,
        "target_layer": target_layer,
        "contamination_detected": compiled.contamination_detected,
        "intention_vector": compiled.intention_vector,
        "response": generation_result["response"],
        "metadata": {
            "eval_count": generation_result.get("eval_count", 0),
            "total_duration_ns": generation_result.get("total_duration_ns", 0),
            "carrier_capable": generation_result.get("carrier_capable", False),
            "echo_mode": generation_result.get("echo_mode", False),
            "session_id": session_id,
            "ollama_tag": generation_result.get("ollama_tag"),
            "carrier_anchor_applied": False,
            "memory_chunks_used": 0,
            "memory_chunk_previews": [],
        },
        "compiled_intent": compiled.to_dict(),
    }
