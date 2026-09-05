"""Shared task envelope for local/cloud code backends (Ollama coder, CC CLI, …)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CodeTaskRequest:
    route_id: str
    route_class: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    prompt: str = ""
    max_tokens: int = 2048
    temperature: float = 0.3
    timeout: float = 300.0
    stream: bool = False
    vision: bool = False
    upstream_model: str | None = None
    cli_model: str | None = None
    cli_label: str | None = None

    def effective_prompt(self) -> str:
        if self.prompt.strip():
            return self.prompt.strip()
        user_parts: list[str] = []
        for msg in self.messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                user_parts.append(content)
        return "\n\n".join(p for p in user_parts if p).strip()


@dataclass(frozen=True)
class CodeTaskResponse:
    text: str
    backend_id: str
    model: str
    route_class: str | None = None
    error: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    finish_reason: str = "stop"
    usage: dict[str, Any] | None = None
    resolved_models: tuple[str, ...] = ()
    label: str | None = None
    proof: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.text.strip())

    def to_meta_dict(self) -> dict[str, Any]:
        meta = {
            "route": self.backend_id,
            "backend_id": self.backend_id,
            "model": self.model,
            "cli_model": self.model if self.backend_id == "cc_cli" else None,
            "label": self.label,
            "resolved_models": list(self.resolved_models),
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
        }
        return {k: v for k, v in meta.items() if v is not None}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
