"""Map CodeTaskResponse → gateway substrate airlock fields."""
from __future__ import annotations

import asyncio
from typing import Any

from code_task.backends.cc_cli import execute as execute_cc_cli
from code_task.backends.ollama import execute as execute_ollama
from code_task.contract import CodeTaskRequest, CodeTaskResponse
from code_task.manual_backend import task_scoped_cc_prompt
from code_task.registry import BackendTarget


def build_code_task_request(
    *,
    route_id: str,
    route_class: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    timeout: float,
    target: BackendTarget,
) -> CodeTaskRequest:
    prompt = task_scoped_cc_prompt(messages, route_class=route_class)
    return CodeTaskRequest(
        route_id=route_id,
        route_class=route_class,
        messages=messages if target.backend_id != "cc_cli" else [],
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        cli_model=target.model if target.backend_id == "cc_cli" else None,
        cli_label="grid-manual-cc",
    )


async def execute_manual_backend(
    req: CodeTaskRequest,
    target: BackendTarget,
) -> CodeTaskResponse:
    if target.backend_id == "cc_cli":
        return await asyncio.to_thread(
            execute_cc_cli,
            req,
            cli_model=target.model,
            label="grid-manual-cc",
            backend_id="cc_cli",
        )
    if target.backend_id.startswith("ollama"):
        return await execute_ollama(
            req,
            endpoint=target.endpoint,
            model=target.model,
            backend_id=target.backend_id,
        )
    raise ValueError(f"execute_manual_backend: unsupported target {target.backend_id}")


def cc_cli_failure_proof(resp: CodeTaskResponse) -> dict[str, Any]:
    meta = resp.to_meta_dict()
    meta["cc_cli_failed"] = True
    meta["request_id"] = resp.proof.get("request_id")
    if resp.proof.get("stderr"):
        meta["stderr"] = resp.proof["stderr"]
    if resp.proof.get("exit_code") is not None:
        meta["exit_code"] = resp.proof["exit_code"]
    return meta


def success_proof(resp: CodeTaskResponse, *, aster_compile_called: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    proof: dict[str, Any] = {
        "raw_response_received": True,
        "code_backend": resp.backend_id,
        "backend_id": resp.backend_id,
        "cost_usd": resp.cost_usd,
        "duration_ms": resp.duration_ms,
        "resolved_models": list(resp.resolved_models),
        "aster_compile_called": aster_compile_called,
        **resp.proof,
    }
    usage = dict(resp.usage or {})
    usage["finish_reason"] = resp.finish_reason
    usage["cost_usd"] = resp.cost_usd
    usage["duration_ms"] = resp.duration_ms
    usage["backend_id"] = resp.backend_id
    return proof, usage
