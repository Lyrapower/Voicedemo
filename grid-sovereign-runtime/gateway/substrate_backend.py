"""Gateway shim — re-exports code_task registry for :8501 substrate routing."""
from __future__ import annotations

from typing import Any

from code_task.backends.ollama import chat_payload as ollama_chat_payload
from code_task.registry import BackendTarget as SubstrateTarget
from code_task.registry import resolve_code_backend

__all__ = ["SubstrateTarget", "ollama_chat_payload", "resolve_substrate_target"]


def resolve_substrate_target(
    config: dict[str, Any],
    *,
    route_class: str | None = None,
    vision: bool = False,
    upstream_model: str | None = None,
    manual_backend_id: str | None = None,
    body: dict[str, Any] | None = None,
) -> SubstrateTarget:
    return resolve_code_backend(
        config,
        route_class=route_class,
        vision=vision,
        upstream_model=upstream_model,
        manual_backend_id=manual_backend_id,
        body=body,
    )
