"""Ollama coder execution — local HTTP /api/chat only."""
from __future__ import annotations

from typing import Any

import httpx

from code_task.contract import CodeTaskRequest, CodeTaskResponse


def chat_payload(
    messages: list,
    *,
    model: str,
    stream: bool,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {
            "num_predict": int(max_tokens),
            "temperature": float(temperature),
        },
    }


async def execute(
    request: CodeTaskRequest,
    *,
    endpoint: str,
    model: str,
    backend_id: str = "ollama_coder",
) -> CodeTaskResponse:
    async with httpx.AsyncClient(timeout=request.timeout) as client:
        r = await client.post(
            endpoint,
            json=chat_payload(
                request.messages,
                model=model,
                stream=False,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            ),
        )
        r.raise_for_status()
        raw = r.json().get("message", {}).get("content", "")
    return CodeTaskResponse(
        text=str(raw or ""),
        backend_id=backend_id,
        model=model,
        route_class=request.route_class,
        finish_reason="stop",
        usage={"finish_reason": "stop", "truncated": False, "content_tokens": len(str(raw).split())},
        proof={"raw_response_received": True},
    )
