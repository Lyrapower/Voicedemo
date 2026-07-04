from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.adapters.aster_adapter import AsterAdapter
from app.adapters.claude_adapter import ClaudeAdapter
from app.router.compiled_memory import build_compiled_memory, load_compiled_context


ROOT = Path(__file__).resolve().parents[2]


def _load_routing_policy() -> dict[str, Any]:
    path = ROOT / "config" / "routing_policy.yaml"
    text = path.read_text(encoding="utf-8", errors="ignore")
    external_enabled = "external_enabled: true" in text.lower()
    coordination_mode = "coordination_mode: false" not in text.lower()
    dry_run = "dry_run: false" not in text.lower()
    return {
        "routing": {
            "external_enabled": external_enabled,
            "coordination_mode": coordination_mode,
            "dry_run": dry_run,
        },
        "kill_switch": {
            "file": "data/execution/KILL_EXTERNAL",
        },
        "logs": {
            "external_calls": "logs/external_calls.jsonl",
        },
    }


class ReviewPipeline:
    def __init__(self) -> None:
        self.config = _load_routing_policy()
        self.claude: ClaudeAdapter | None = None
        self.aster: AsterAdapter | None = None
        self.initialized = False
        build_compiled_memory()
        if self._is_external_enabled():
            self._initialize_adapters()

    def _is_external_enabled(self) -> bool:
        kill_file = ROOT / self.config["kill_switch"]["file"]
        if kill_file.exists():
            return False
        return bool(self.config["routing"]["external_enabled"])

    def _initialize_adapters(self) -> None:
        dry_run = bool(self.config["routing"]["dry_run"])
        self.claude = ClaudeAdapter(dry_run=dry_run)
        self.aster = AsterAdapter(dry_run=dry_run)
        self.claude.register_peer(self.aster)
        self.aster.register_peer(self.claude)
        self.initialized = True

    def _log_call(self, agent: str, success: bool, latency_ms: int, error: str | None = None) -> None:
        path = ROOT / self.config["logs"]["external_calls"]
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "agent": agent,
            "success": success,
            "latency_ms": latency_ms,
            "error": error,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def run(self, spec_content: str, skip_claude: bool = False) -> dict[str, Any]:
        build_compiled_memory()
        compiled_context = load_compiled_context()
        if not self._is_external_enabled():
            return {
                "ok": False,
                "error": "External APIs disabled by policy or kill switch.",
                "compiled_memory_only": True,
                "compiled_context_source": "knowledge/compiled/*.md",
                "compiled_context_preview": compiled_context[:400],
            }
        if not self.initialized or self.claude is None or self.aster is None:
            return {
                "ok": False,
                "error": "Adapters not initialized.",
            }

        claude_result = None
        if not skip_claude:
            claude_result = self.claude.call(spec_content, mode="spec_audit")
            self._log_call("claude", claude_result["ok"], claude_result["latency_ms"], claude_result.get("error"))

        aster_result = self.aster.call(
            spec_content,
            mode="compiler",
            claude_review=claude_result["reply"] if claude_result else None,
        )
        self._log_call("aster", aster_result["ok"], aster_result["latency_ms"], aster_result.get("error"))

        review_dir = ROOT / "deliver" / "review"
        cursor_dir = ROOT / "deliver" / "cursor"
        review_dir.mkdir(parents=True, exist_ok=True)
        cursor_dir.mkdir(parents=True, exist_ok=True)
        if claude_result:
            (review_dir / "claude_review.json").write_text(
                json.dumps(claude_result["reply"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        (cursor_dir / "CursorPack.md").write_text(
            aster_result["reply"].get("CURSORPACK", aster_result["raw"]),
            encoding="utf-8",
        )

        return {
            "ok": True,
            "claude_review": claude_result["reply"] if claude_result else None,
            "aster_build": aster_result["reply"],
            "acceptance_cmd": aster_result["reply"].get("acceptance_cmd", "./scripts/accept_routing.sh"),
            "compiled_context_source": "knowledge/compiled/*.md",
        }
