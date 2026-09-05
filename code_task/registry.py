"""Backend registry — selects execution lane, not transport details."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from code_task.manual_backend import (
    MANUAL_BACKEND_IDS,
    TASK_SCOPED_ROUTES,
    effective_manual_backend_id,
)


@dataclass(frozen=True)
class BackendTarget:
    backend_id: str
    endpoint: str
    model: str
    route_class: str | None = None
    coder_routed: bool = False
    manual: bool = False


def _coder_routes(config: dict[str, Any]) -> set[str]:
    raw = config.get("coder_routes") or ["compile", "task"]
    if isinstance(raw, str):
        return {raw.strip()} if raw.strip() else set()
    return {str(x).strip() for x in raw if str(x).strip()}


def _ollama_coder_target(config: dict[str, Any], route: str, *, manual: bool) -> BackendTarget:
    coder_model = str(
        config.get("ollama_coder_model") or config.get("ollama_model") or "qwen2.5-coder:7b"
    ).strip()
    return BackendTarget(
        backend_id="ollama_coder",
        endpoint=str(config.get("ollama_endpoint") or "http://localhost:11434/api/chat"),
        model=coder_model,
        route_class=route,
        coder_routed=True,
        manual=manual,
    )


def _cc_cli_target(
    config: dict[str, Any],
    route: str,
    *,
    cli_model_override: str | None = None,
) -> BackendTarget:
    model = str(
        cli_model_override
        or config.get("cc_cli_model")
        or os.getenv("GRID_CC_CLI_MODEL", os.getenv("DISTILL_CLI_MODEL", "claude-fable-5"))
    ).strip()
    return BackendTarget(
        backend_id="cc_cli",
        endpoint="",
        model=model,
        route_class=route,
        coder_routed=True,
        manual=True,
    )


def _kimi_k25_cloud_target(config: dict[str, Any], route: str) -> BackendTarget:
    model = str(config.get("kimi_k25_cloud_model") or "kimi-k2.6:cloud").strip()  # K2.6 default
    endpoint = str(
        config.get("kimi_k25_cloud_endpoint")
        or config.get("ollama_endpoint")
        or "http://localhost:11434/api/chat"
    ).strip()
    return BackendTarget(
        backend_id="kimi_k25_cloud",
        endpoint=endpoint,
        model=model,
        route_class=route,
        coder_routed=False,
        manual=True,
    )


def _glm53_flash_cloud_target(config: dict[str, Any], route: str) -> BackendTarget:
    model = str(config.get("glm53_flash_cloud_model") or "glm-5.3-flash:cloud").strip()
    endpoint = str(
        config.get("glm53_flash_cloud_endpoint")
        or config.get("ollama_endpoint")
        or "http://localhost:11434/api/chat"
    ).strip()
    return BackendTarget(
        backend_id="glm53_flash_cloud",
        endpoint=endpoint,
        model=model,
        route_class=route,
        coder_routed=False,
        manual=True,
    )


def _glm52_cloud_target(config: dict[str, Any], route: str) -> BackendTarget:
    model = str(config.get("glm52_cloud_model") or "glm-5.2:cloud").strip()
    endpoint = str(
        config.get("glm52_cloud_endpoint")
        or config.get("ollama_endpoint")
        or "http://localhost:11434/api/chat"
    ).strip()
    return BackendTarget(
        backend_id="glm52_cloud",
        endpoint=endpoint,
        model=model,
        route_class=route,
        coder_routed=False,
        manual=True,
    )


def _deepseek_v4_cloud_target(config: dict[str, Any], route: str) -> BackendTarget:
    model = str(config.get("deepseek_v4_cloud_model") or "deepseek-v4-pro:cloud").strip()
    endpoint = str(
        config.get("deepseek_v4_cloud_endpoint")
        or config.get("ollama_endpoint")
        or "http://localhost:11434/api/chat"
    ).strip()
    return BackendTarget(
        backend_id="deepseek_v4_cloud",
        endpoint=endpoint,
        model=model,
        route_class=route,
        coder_routed=False,
        manual=True,
    )


def resolve_code_backend(
    config: dict[str, Any],
    *,
    route_class: str | None = None,
    vision: bool = False,
    upstream_model: str | None = None,
    manual_backend_id: str | None = None,
    body: dict[str, Any] | None = None,
) -> BackendTarget:
    """compile/task default ollama_coder; cc_cli only when explicitly requested."""
    route = (route_class or "chat").strip() or "chat"
    if route == "candidate":
        bid = manual_backend_id or "glm52_cloud"
        if bid == "glm52_cloud":
            return _glm52_cloud_target(config, route)
        if bid == "glm53_flash_cloud":
            return _glm53_flash_cloud_target(config, route)
        if bid == "kimi_k25_cloud":
            return _kimi_k25_cloud_target(config, route)
        if bid == "deepseek_v4_cloud":
            return _deepseek_v4_cloud_target(config, route)
        raise ValueError(f"unsupported candidate backend_id: {bid}")

    if vision:
        model = str(config.get("vl_model") or upstream_model or config.get("openai_model") or "")
        return BackendTarget(
            backend_id="lm_studio",
            endpoint=str(config["openai_endpoint"]),
            model=model,
            route_class=route,
        )

    if route in TASK_SCOPED_ROUTES:
        bid = manual_backend_id
        if bid is None and body is not None:
            bid = effective_manual_backend_id(body, route_class=route)
            if bid == "lm_studio":
                bid = "ollama_coder"
        elif bid is None:
            bid = "ollama_coder"
        if bid == "cc_cli":
            cli_override = None
            if body is not None:
                raw = body.get("cli_model") or body.get("cc_cli_model")
                if raw is not None and str(raw).strip():
                    cli_override = str(raw).strip()
            return _cc_cli_target(config, route, cli_model_override=cli_override)
        if bid in ("ollama_coder", "ollama"):
            return _ollama_coder_target(config, route, manual=bool(manual_backend_id))
        if bid in MANUAL_BACKEND_IDS:
            raise ValueError(f"unsupported manual backend_id for route {route}: {bid}")

    coder_on = bool(config.get("coder_routing_enabled"))
    if coder_on and route in _coder_routes(config):
        return _ollama_coder_target(config, route, manual=False)

    backend = str(config.get("backend") or "openai")
    if backend == "ollama":
        coder_model = str(
            config.get("ollama_coder_model") or config.get("ollama_model") or "qwen2.5-coder:7b"
        ).strip()
        return BackendTarget(
            backend_id="ollama",
            endpoint=str(config.get("ollama_endpoint") or "http://localhost:11434/api/chat"),
            model=str(config.get("ollama_model") or coder_model),
            route_class=route,
        )

    model = str(upstream_model or config.get("openai_model") or "")
    return BackendTarget(
        backend_id="lm_studio",
        endpoint=str(config["openai_endpoint"]),
        model=model,
        route_class=route,
    )
