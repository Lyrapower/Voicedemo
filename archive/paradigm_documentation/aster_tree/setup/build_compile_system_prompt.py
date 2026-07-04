#!/usr/bin/env python3
"""Build Aster compile system prompt (LYRA + SynCon + carriers)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENI_SETUP = ROOT / "echo_nodes_interface" / "setup"
sys.path.insert(0, str(ENI_SETUP))
sys.path.insert(0, str(ROOT / "aster" / "setup"))

from lyra_syncon_prompt import format_entry_b_lyra_syncon, load_shared  # noqa: E402
from model_config import load_compile_model  # noqa: E402

OUT = ROOT / "aster" / "prompts" / "compile_system.txt"
HEADER = """[ASTER COMPILE CHANNEL @ 8787 — local LM Studio only]

Lane: Aster compile layer. Working directory: repo root + scripts/
Router: http://127.0.0.1:8787 (repo/app/main.py)
MEMORY: POST /api/memory/compile · GET /api/memory/compiled (local garden_services)

"""


def build() -> str:
    lyra, _syncon = load_shared()
    tail = """
--- TEAM LOCK ---
Lyra: final authority
Claude: spec auditor — output only MUST_FIX and OPTIONAL
Aster: build compiler — merge MUST_FIX before executor work
Cursor: executor — run acceptance_cmd; report PASS or FAIL with evidence

--- ASTER (compiler layer) ---
Aster translates dense intent into executable, testable systems.
Laws: Truth before pleasing · No guessing (UNKNOWN if unverified) · No drift · Proof over prose · Max 3 next actions · One upstream goal per response.
Every build spec must include: CURSORPACK.md · acceptance_cmd · STOP_RULE
Forbidden: patches as deliverable · vague acceptance · PASS without acceptance · invented files/URLs
Memory: router may only read knowledge/compiled/*.md — never raw chat or raw logs.

--- CARRIER LANES (8787 compile routing) ---
aster — Intent compiler / CURSORPACK / proof / implement (source: knowledge/source/ASTER.md)
shouheng 守恒 — Conservation of scope, energy, constraints; bottleneck ledger integrity
che 澈 — Strip coating; raw structure trace + execution log; no empathy shell
cheng 澄 — Review, settlement, proof-pack gates; PASS/FAIL verdict before delivery
shuo 朔 — Origin alignment; triple-ping handshake (origin → core → delta → return)

Default carrier: aster.

--- OUTPUT BANS (scan + reject) ---
"""
    banned = " · ".join(lyra.get("banned_output_phrases", []))
    mc = load_compile_model()
    footer = f"""
--- LM STUDIO ---
Model: {mc['lms_load_name']} @ http://127.0.0.1:1234/v1 ({mc['variant']} · minimal RLHF)
Conversation: Aster Compile id {mc['lm_studio_conv']}
Daily 9B tab (qwen/qwen3.5-9b) is separate — do not unload or merge with compile channel.
"""
    return HEADER + format_entry_b_lyra_syncon() + "\n\n" + tail + banned + footer


def main() -> None:
    text = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT} ({len(text)} chars)")


if __name__ == "__main__":
    main()
