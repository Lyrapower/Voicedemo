"""Ollama Cloud GLM 5.2 candidate backend — thinking blackboxed.

Invariants (glm52-base-swap v2):
- Core chain text-only; pixels only in VL bypass (K2.6), never in GLM call.
- Model identity passthrough: response model field is never relabeled.
- No silent fallback to K2.6 or other models on GLM failure.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from code_task.candidate_contract import (
    GLM52_CANDIDATE_SOURCE,
    CandidateResponse,
    ThinkingMeta,
)
from code_task.glm52_pricing import enrich_glm52_usage
from code_task.glm52_input_scope import build_task_scoped_messages

MIN_NUM_PREDICT = 512


def _extract_thinking(message: dict[str, Any], body: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("thinking", "reasoning_content", "reasoning"):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    for key in ("thinking", "reasoning_content", "reasoning"):
        val = body.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    return "\n".join(parts)


def _thinking_meta(thinking: str) -> ThinkingMeta:
    if not thinking:
        return ThinkingMeta(present=False, length=0, hash=None)
    digest = hashlib.sha256(thinking.encode("utf-8")).hexdigest()[:16]
    return ThinkingMeta(present=True, length=len(thinking), hash=digest)


def chat_payload(
    messages: list[dict[str, Any]],
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    think: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": max(int(max_tokens), MIN_NUM_PREDICT),
            "temperature": float(temperature),
        },
    }
    # 必须显式布尔:省略键时 Ollama Cloud 常默认开 think → content 空(Cloud 长记忆事故)
    payload["think"] = bool(think)
    return payload


async def execute_candidate(
    *,
    request_id: str,
    prompt: str,
    endpoint: str,
    model: str,
    task_label: str | None = None,
    images: Any = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    timeout: float = 300.0,
) -> CandidateResponse:
    if images:
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            done_reason="input_rejected",
            source=GLM52_CANDIDATE_SOURCE,
            model=model,
            error={"type": "input_scope", "reason": "GLM 5.2 candidate is text-only; use VL bypass for images"},
        )

    try:
        messages = build_task_scoped_messages(
            prompt=prompt,
            task_label=task_label,
            images=None,
        )
    except ValueError as exc:
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            done_reason="input_rejected",
            source=GLM52_CANDIDATE_SOURCE,
            model=model,
            error={"type": "input_scope", "reason": str(exc)},
        )

    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                endpoint,
                json=chat_payload(
                    messages,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
            )
            r.raise_for_status()
            body = r.json()
    except httpx.HTTPStatusError as exc:
        detail = str(exc)[:400]
        try:
            err_body = exc.response.json()
            if isinstance(err_body, dict) and err_body.get("error"):
                detail = str(err_body["error"])[:400]
        except Exception:
            pass
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            done_reason="upstream_error",
            source=GLM52_CANDIDATE_SOURCE,
            model=model,
            error={"type": type(exc).__name__, "reason": detail},
            usage={"latency_ms": int((time.time() - started) * 1000)},
        )

    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    thinking = _extract_thinking(message, body)
    meta = _thinking_meta(thinking)
    content = str(message.get("content") or "").strip()
    done = str(body.get("done_reason") or message.get("done_reason") or "stop")
    upstream_model = str(body.get("model") or message.get("model") or model).strip()
    raw_usage = dict(body.get("usage") or {})
    for key in (
        "prompt_eval_count",
        "eval_count",
        "total_duration",
        "load_duration",
        "prompt_eval_duration",
        "eval_duration",
    ):
        if key in body and key not in raw_usage:
            raw_usage[key] = body[key]
    usage = enrich_glm52_usage(raw_usage)
    usage["latency_ms"] = int((time.time() - started) * 1000)
    usage["backend_id"] = GLM52_CANDIDATE_SOURCE
    usage["ollama_cloud"] = True

    if not content:
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            content="",
            done_reason=done or "empty_content",
            source=GLM52_CANDIDATE_SOURCE,
            model=upstream_model,
            usage=usage,
            thinking_meta=meta,
            error={"type": "empty_content", "reason": "message.content empty after thinking strip"},
        )

    return CandidateResponse(
        request_id=request_id,
        ok=True,
        content=content,
        done_reason=done,
        source=GLM52_CANDIDATE_SOURCE,
        usage=usage,
        thinking_meta=meta,
        model=upstream_model,
    )


def shadow_candidate_response(*, request_id: str, prompt: str, images: Any = None) -> CandidateResponse:
    """Validate scoping only — no cloud call."""
    if images:
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            done_reason="input_rejected",
            source=GLM52_CANDIDATE_SOURCE,
            error={"type": "input_scope", "reason": "GLM 5.2 candidate is text-only"},
        )
    try:
        build_task_scoped_messages(prompt=prompt, task_label="shadow", images=None)
    except ValueError as exc:
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            done_reason="input_rejected",
            source=GLM52_CANDIDATE_SOURCE,
            error={"type": "input_scope", "reason": str(exc)},
        )
    return CandidateResponse(
        request_id=request_id,
        ok=True,
        content="[shadow] input scope accepted — cloud call skipped",
        done_reason="shadow",
        source=GLM52_CANDIDATE_SOURCE,
        usage={"mode": "shadow", "backend_id": GLM52_CANDIDATE_SOURCE},
        thinking_meta=ThinkingMeta(present=False, length=0, hash=None),
    )
