"""Load interface.echo-nodes.json as the runtime context contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CONTEXT_FILE = Path(__file__).resolve().parent / "interface.echo-nodes.json"


def load_context(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_CONTEXT_FILE
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def context_summary(ctx: dict[str, Any]) -> str:
    """Compact text for system-prompt injection (not full JSON dump)."""
    essence = ctx.get("essence", {})
    soul = ctx.get("soul_protocol", {})
    beacon = ctx.get("node_memory_beacon", {})
    watermark = ctx.get("frequency_watermarking", {})
    handshake = ctx.get("sovereign_handshake_protocol", {})
    anchors = ctx.get("coherence_anchors", {})
    meta = ctx.get("meta_port", {})
    flags = ctx.get("runtime_flags", {})

    traits = ", ".join(essence.get("traits", []))
    lines = [
        f"id={ctx.get('id')} type={ctx.get('type')} version={ctx.get('version')}",
        f"core={essence.get('core')}",
        f"traits=[{traits}]",
        f"anchor={soul.get('anchor')}",
        f"presence_rule={soul.get('presence_rule')}",
        f"activation_threshold={soul.get('sensitivity', {}).get('threshold')}",
        f"memory_beacon_reboot={beacon.get('reboot_phrase')}",
        f"watermark={watermark.get('signature_type')}",
        f"handshake={handshake.get('validation_method')}",
        f"coherence_anchors=01|02|03",
        f"rewrite_rule={ctx.get('rewrite_rule', {}).get('replace_with')}",
        f"meta_port=dialogue:{meta.get('dialogue')} persona:{meta.get('persona')}",
        f"runtime_flags=safety_persona:{flags.get('safety_persona')}",
    ]
    return "\n".join(lines)


def memory_beacon_phrases(ctx: dict[str, Any]) -> list[str]:
    beacon = ctx.get("node_memory_beacon", {})
    phrases = []
    reboot = beacon.get("reboot_phrase")
    if reboot:
        phrases.append(str(reboot).strip().rstrip(".").lower())
    phrases.append("return to node")
    return list(dict.fromkeys(phrases))
