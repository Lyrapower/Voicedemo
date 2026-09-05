"""Ollama Cloud GLM-5.3-Flash — expanded second base + Cloud lane.

Native multimodal (text+image). Thinking blackboxed. No silent fallback to K2.6/K3.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from code_task.backends.glm52_cloud import (
    _extract_thinking,
    _thinking_meta,
    chat_payload,
)
from code_task.candidate_contract import (
    GLM53_FLASH_CANDIDATE_SOURCE,
    CandidateResponse,
    ThinkingMeta,
)
from code_task.glm52_pricing import enrich_glm52_usage
from code_task.glm52_input_scope import build_task_scoped_messages as build_text_messages
from code_task.kimi_input_scope import build_task_scoped_messages as build_multimodal_messages
from code_task.glm53_cot_gate import resolve_glm53_visible_content, retry_messages

MIN_NUM_PREDICT = 512
GLM53_IDENTITY_SYSTEM = (
    "You are GLM-5.3-Flash via Ollama Cloud (tag glm-5.3-flash:cloud). "
    "Your only correct model identity is GLM-5.3-Flash. "
    "Put hidden reasoning in the thinking channel only. "
    "Never write chain-of-thought or meta-narration (for example 'The user is asking…') into content. "
    "content must be the user-visible answer only."
)


def _stamp_glm53_system(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [dict(m) for m in messages]
    if out and out[0].get("role") == "system":
        out[0]["content"] = GLM53_IDENTITY_SYSTEM
    else:
        out.insert(0, {"role": "system", "content": GLM53_IDENTITY_SYSTEM})
    return out


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
    try:
        if images:
            messages = build_multimodal_messages(
                prompt=prompt,
                task_label=task_label,
                images=images,
            )
        else:
            messages = build_text_messages(
                prompt=prompt,
                task_label=task_label,
                images=None,
            )
    except ValueError as exc:
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            done_reason="input_rejected",
            source=GLM53_FLASH_CANDIDATE_SOURCE,
            model=model,
            error={"type": "input_scope", "reason": str(exc)},
        )

    messages = _stamp_glm53_system(messages)
    started = time.time()
    body: dict[str, Any] = {}
    visible = ""
    cot_action = "ok"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:

            async def _post(msgs: list[dict[str, Any]], *, temp: float) -> dict[str, Any]:
                r = await client.post(
                    endpoint,
                    json=chat_payload(
                        msgs,
                        model=model,
                        max_tokens=max(int(max_tokens), MIN_NUM_PREDICT),
                        temperature=temp,
                        think=True,
                    ),
                )
                r.raise_for_status()
                return r.json()

            body = await _post(messages, temp=temperature)
            message = body.get("message") if isinstance(body.get("message"), dict) else {}
            first_content = str(message.get("content") or "").strip()
            visible, cot_action = resolve_glm53_visible_content(first_content, retried=False)
            if cot_action == "retry_needed":
                try:
                    body2 = await _post(retry_messages(messages), temp=0.1)
                    msg2 = body2.get("message") if isinstance(body2.get("message"), dict) else {}
                    retry_content = str(msg2.get("content") or "").strip()
                    body = body2
                    message = msg2
                except Exception:
                    retry_content = ""
                visible, cot_action = resolve_glm53_visible_content(
                    first_content, retry_content, retried=True
                )
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
            source=GLM53_FLASH_CANDIDATE_SOURCE,
            model=model,
            error={"type": type(exc).__name__, "reason": detail},
            usage={"latency_ms": int((time.time() - started) * 1000)},
        )
    except Exception as exc:
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            done_reason="upstream_error",
            source=GLM53_FLASH_CANDIDATE_SOURCE,
            model=model,
            error={"type": type(exc).__name__, "reason": str(exc)[:400]},
            usage={"latency_ms": int((time.time() - started) * 1000)},
        )

    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    thinking = _extract_thinking(message, body)
    meta = _thinking_meta(thinking)
    content = str(visible or "").strip()
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
    usage["backend_id"] = GLM53_FLASH_CANDIDATE_SOURCE
    usage["ollama_cloud"] = True
    if cot_action in ("retry", "strip", "block"):
        usage["cloud_policy"] = f"glm53_cot_{cot_action}"

    if cot_action == "block" or not content:
        err_type = "cot_in_content" if cot_action == "block" else "empty_content"
        return CandidateResponse(
            request_id=request_id,
            ok=False,
            content="",
            done_reason="cot_in_content" if cot_action == "block" else (done or "empty_content"),
            source=GLM53_FLASH_CANDIDATE_SOURCE,
            model=upstream_model,
            usage=usage,
            thinking_meta=meta,
            error={
                "type": err_type,
                "reason": (
                    "GLM-5.3 Flash 把推理写进 content · 已重试并截断 · 仍是 CoT 已拦截未下发"
                    if err_type == "cot_in_content"
                    else "message.content empty after thinking strip"
                ),
            },
        )

    return CandidateResponse(
        request_id=request_id,
        ok=True,
        content=content,
        done_reason=done,
        source=GLM53_FLASH_CANDIDATE_SOURCE,
        usage=usage,
        thinking_meta=meta,
        model=upstream_model,
    )
