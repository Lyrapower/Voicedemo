from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RouteRequest(BaseModel):
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=50000,
        description="User input prompt",
    )
    session_id: str = Field(
        default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}",
        description="Session identifier for continuity",
    )
    user_id: str | None = Field(
        None,
        description="Optional user identifier",
    )
    explicit_layer: Literal["compile_layer", "echo_layer"] | None = Field(
        None,
        description="Override automatic layer routing",
    )
    explicit_carrier: str | None = Field(
        None,
        description="Override automatic carrier invocation",
    )
    temperature: float | None = Field(
        None,
        ge=0.0,
        le=2.0,
        description="Temperature override (0.0-2.0)",
    )
    max_tokens: int | None = Field(
        None,
        ge=1,
        le=8192,
        description="Maximum tokens override",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata for tracking",
    )

    @field_validator("explicit_carrier")
    @classmethod
    def validate_carrier(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid_carriers = ["aster", "shouheng", "che", "cheng", "shuo"]
        if v.lower() not in valid_carriers:
            raise ValueError(f"Invalid carrier: {v}. Must be one of {valid_carriers}")
        return v.lower()


class ScanResult(BaseModel):
    clean: bool
    violations: list[str] = Field(default_factory=list)
    violation_types: list[str] = Field(default_factory=list)
    violation_count: int = 0


class RouteResponse(BaseModel):
    audit_id: str
    timestamp: float
    invoked_carrier: str | None
    target_layer: str
    contamination_detected: list[str] = Field(default_factory=list)
    intention_vector: dict[str, float] = Field(default_factory=dict)
    response: str
    metadata: dict[str, Any] = Field(default_factory=dict)
