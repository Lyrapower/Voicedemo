from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


class AsterAdapter:
    def __init__(self, model: str = "gpt-4", dry_run: bool = True):
        self.model = model
        self.dry_run = dry_run
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.enabled = bool(self.api_key) and not dry_run
        self.system_context = self._load_context()
        self.peer_adapter = None

    def _load_context(self) -> str:
        return "Aster compile mode."

    def register_peer(self, peer_adapter: Any) -> dict[str, str]:
        self.peer_adapter = peer_adapter
        return {"status": "peer_registered", "peer": "claude"}

    def update_context(self) -> dict[str, str]:
        self.system_context = self._load_context()
        return {"status": "context_updated"}

    def call(
        self,
        prompt: str,
        mode: str = "compiler",
        conversation_history: list[dict[str, Any]] | None = None,
        max_tokens: int = 4000,
        claude_review: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = datetime.utcnow()
        if self.dry_run or not self.enabled:
            raw = (
                "CURSORPACK.md\n"
                "Local-first build pack is blocked for external execution in this step.\n\n"
                "acceptance_cmd: ./scripts/accept_routing.sh\n\n"
                "STOP_RULE\n"
                "Stop after PASS or FAIL with proof paths.\n"
            )
            latency_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
            return {
                "ok": True,
                "reply": {
                    "CURSORPACK": "Local-first build pack is blocked for external execution in this step.",
                    "acceptance_cmd": "./scripts/accept_routing.sh",
                    "STOP_RULE": "Stop after PASS or FAIL with proof paths.",
                    "NEXT": [],
                    "raw": raw,
                },
                "raw": raw,
                "latency_ms": latency_ms,
                "model": self.model,
                "mode": mode,
                "dry_run": True,
            }
        raise RuntimeError("External Aster execution is intentionally disabled in this step")
