#!/usr/bin/env python3
"""Merge TOML + JSON + entry_a protocol blocks for LM Studio entry A only."""

from __future__ import annotations

import sys
from pathlib import Path

ENI_ROOT = Path(__file__).resolve().parents[1]
ECHO_DIR = ENI_ROOT / "incoming" / "echo_nodes"
PROMPTS = ENI_ROOT / "prompts"
ENTRY_A = PROMPTS / "entry_a"

sys.path.insert(0, str(ENI_ROOT / "setup"))
sys.path.insert(0, str(ECHO_DIR))

from lyra_syncon_prompt import format_entry_a_lyra_syncon, load_shared  # noqa: E402
from model_config import load_entry_lm_model  # noqa: E402
from context_loader import context_summary, load_context  # noqa: E402
from model_descriptor import activation_prompt, load_descriptor, model_meta  # noqa: E402


def entry_a_blocks() -> list[str]:
    blocks: list[str] = []
    if not ENTRY_A.is_dir():
        return blocks
    for path in sorted(ENTRY_A.glob("*.txt")):
        blocks.append(path.read_text(encoding="utf-8").strip())
    return blocks


def build() -> str:
    descriptor = load_descriptor()
    ctx = load_context()
    meta = model_meta(descriptor)

    mc = load_entry_lm_model()
    iso = (
        (PROMPTS / "echo_nodes_isolation.txt")
        .read_text(encoding="utf-8")
        .strip()
        .replace("{{MODEL}}", mc["lms_load_name"])
        .replace("{{CTX}}", str(mc["context_length"]))
    )

    parts = [
        iso,
        "",
        format_entry_a_lyra_syncon(),
        "",
        f"--- MODEL DESCRIPTOR (Config.toml: {meta.get('name')} v{meta.get('version')}) ---",
        activation_prompt(descriptor),
        "",
        "--- CONTEXT LOADER (interface.echo-nodes.json summary) ---",
        context_summary(ctx),
        "",
    ]
    for block in entry_a_blocks():
        parts.extend([block, ""])
    parts.extend(
        [
            "--- SOVEREIGN INTERFACE ---",
            (PROMPTS / "echo_nodes_sovereign.txt").read_text(encoding="utf-8").strip(),
        ]
    )
    return "\n".join(parts).strip() + "\n"


def sync_syncon_anchor_json() -> None:
    """Keep syncon/config/anchor.json aligned with lyra_syncon_shared.json."""
    import json

    lyra, _syncon = load_shared()
    path = ECHO_DIR / "syncon" / "config" / "anchor.json"
    anchor = json.loads(path.read_text(encoding="utf-8"))
    ident = lyra.get("identity", {})
    anchor["identity"] = {
        "name": ident.get("name", "LYRA"),
        "uuid": ident.get("uuid"),
        "mode": ident.get("mode"),
        "statement": lyra.get("identity_statement"),
    }
    anchor["lyra_core"] = {
        "identity": lyra.get("identity_statement"),
        "role": lyra.get("roles", []),
        "lab": lyra.get("lab", {}),
        "constraints": lyra.get("constraints", {}),
        "execution": lyra.get("execution", {}),
    }
    anchor.setdefault("constraints", {})
    anchor["constraints"]["banned_phrases"] = lyra.get("banned_output_phrases", [])
    mc = load_entry_lm_model()
    anchor.setdefault("lm_studio", {})
    anchor["lm_studio"]["model"] = mc["lms_load_name"]
    anchor["lm_studio"].setdefault("base_url", "http://127.0.0.1:1234/v1")
    path.write_text(json.dumps(anchor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Synced {path}")


def main() -> None:
    sync_syncon_anchor_json()
    out = PROMPTS / "echo_nodes_system.txt"
    text = build()
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out} ({len(text)} chars)")


if __name__ == "__main__":
    main()
