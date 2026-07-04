"""Load Entry A system prompt (Lyra + SynCon + Echo protocol) for LM Studio calls."""

from __future__ import annotations

import sys
from pathlib import Path

ENI_ROOT = Path(__file__).resolve().parents[2]
ECHO_PROMPT = ENI_ROOT / "prompts" / "echo_nodes_system.txt"

if str(ENI_ROOT / "setup") not in sys.path:
    sys.path.insert(0, str(ENI_ROOT / "setup"))


def load_echo_system_prompt(*, rebuild: bool = False) -> str:
    if rebuild or not ECHO_PROMPT.exists():
        from build_echo_system_prompt import build

        return build()
    return ECHO_PROMPT.read_text(encoding="utf-8")


def messages_with_echo_system(messages: list[dict]) -> list[dict]:
    """Ensure first message is full Entry A system prompt (Lyra + SynCon + Echo)."""
    system = load_echo_system_prompt()
    if messages and messages[0].get("role") == "system":
        merged = f"{system}\n\n--- SESSION ---\n{messages[0].get('content', '')}"
        return [{"role": "system", "content": merged}] + messages[1:]
    return [{"role": "system", "content": system}] + list(messages)
