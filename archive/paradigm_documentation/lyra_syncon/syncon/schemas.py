from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RouteRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: "sess_" + __import__("uuid").uuid4().hex[:12])
    user_id: str | None = None
    task: Literal["auto", "coding", "writing", "analysis", "chat"] | None = "auto"
    messages: list[dict[str, Any]] = Field(
        ..., description="Chat-style messages: [{role, content}, ...]"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class RouteResponse(BaseModel):
    ok: bool
    request_id: str
    chosen_model: str
    chosen_provider: str
    fallback_used: bool
    route_chain: list[str]
    output_text: str
    freq_flags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
