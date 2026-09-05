"""Candidate lane envelope — isolated cloud inference, no authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


CANDIDATE_SOURCE = "kimi_k25_cloud"
GLM52_CANDIDATE_SOURCE = "glm52_cloud"
GLM53_FLASH_CANDIDATE_SOURCE = "glm53_flash_cloud"
CANDIDATE_ROLE = "candidate"
CANDIDATE_AUTHORITY = "none"


@dataclass(frozen=True)
class ThinkingMeta:
    present: bool = False
    length: int = 0
    hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {"thinking_present": self.present, "thinking_length": self.length}
        if self.hash:
            out["thinking_hash"] = self.hash
        return out


@dataclass(frozen=True)
class CandidateResponse:
    source: str = CANDIDATE_SOURCE
    role: str = CANDIDATE_ROLE
    authority: str = CANDIDATE_AUTHORITY
    memory_write: bool = False
    content: str = ""
    request_id: str = ""
    done_reason: str = "stop"
    usage: dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    error: dict[str, Any] | None = None
    thinking_meta: ThinkingMeta = field(default_factory=ThinkingMeta)
    backend: str = "ollama_cloud"
    model: str = "kimi-k2.6:cloud"

    def to_dict(self) -> dict[str, Any]:
        out = {
            "source": self.source,
            "role": self.role,
            "authority": self.authority,
            "memory_write": self.memory_write,
            "content": self.content,
            "request_id": self.request_id,
            "done_reason": self.done_reason,
            "usage": self.usage,
            "ok": self.ok,
            "backend": self.backend,
            "model": self.model,
            "thinking_meta": self.thinking_meta.to_dict(),
        }
        if self.error:
            out["error"] = self.error
        return out

    def to_log_dict(self) -> dict[str, Any]:
        """Safe audit payload — never includes thinking text or full content."""
        d = self.to_dict()
        d["content_len"] = len(self.content)
        d.pop("content", None)
        return d
