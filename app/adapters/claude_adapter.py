from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


class ClaudeAdapter:
    def __init__(self, model: str = "claude-sonnet-4-20250514", dry_run: bool = True):
        self.model = model
        self.dry_run = dry_run
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.enabled = bool(self.api_key) and not dry_run
        self.system_context = self._load_context()
        self.peer_adapter = None

    def _load_context(self) -> str:
        path = ROOT / "CLAUDE.md"
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
        return "Claude review mode. Output MUST_FIX and OPTIONAL only."

    def register_peer(self, peer_adapter: Any) -> dict[str, str]:
        self.peer_adapter = peer_adapter
        return {"status": "peer_registered", "peer": "aster"}

    def update_context(self) -> dict[str, str]:
        self.system_context = self._load_context()
        return {"status": "context_updated"}

    def call(
        self,
        prompt: str,
        mode: str = "spec_audit",
        conversation_history: list[dict[str, Any]] | None = None,
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        started = datetime.utcnow()
        if self.dry_run or not self.enabled:
            raw = (
                "MUST_FIX:\n"
                "- External review disabled by policy.\n\n"
                "OPTIONAL:\n"
                "- Enable external review later if policy changes.\n\n"
                "REASONING: Local-first mode is active, so Claude review is blocked by design."
            )
            latency_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
            return {
                "ok": True,
                "reply": {
                    "MUST_FIX": ["External review disabled by policy."],
                    "OPTIONAL": ["Enable external review later if policy changes."],
                    "REASONING": "Local-first mode is active, so Claude review is blocked by design.",
                    "structured": True,
                },
                "raw": raw,
                "latency_ms": latency_ms,
                "model": self.model,
                "mode": mode,
                "dry_run": True,
            }
        raise RuntimeError("External Claude execution is intentionally disabled in this step")
