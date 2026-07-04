#!/usr/bin/env python3
"""Ensure Entry B LM Studio + HTTP prompt includes full LYRA/SynCon from shared config."""

from __future__ import annotations

import sys
from pathlib import Path

ENI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENI_ROOT / "setup"))

from lyra_syncon_prompt import format_entry_b_lyra_syncon  # noqa: E402
from model_config import load_entry_lm_model  # noqa: E402

OUT = ENI_ROOT / "prompts" / "entry_b_compile_system.txt"
HEADER = """[ENTRY: Compile Layer + Particle Field — Entry B @ 8787 — DO NOT MIX WITH ENTRY A Echo]

Lane: Aster compile layer only. Not Echo Nodes Interface (8500).
Working directory: repo root + scripts/ (particle: scripts/sound_lab_fallback.py)
Router: http://127.0.0.1:8787 (repo/app/main.py)
MEMORY: POST /api/memory/compile · GET /api/memory/compiled (local garden_services — never proxy to 8500)

"""


def build() -> str:
    from lyra_syncon_prompt import load_shared

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

Default carrier: aster. Do not simulate Echo frequency interface behavior in this entry.

--- CHENXI / GRID (parallel, not merged here) ---
When Grid app/main.py runs separately: /health · /map_intent · /transmit only.
/transmit = sole raw consciousness stream. Do not chain Compiler→LLM in one POST /route.

--- OUTPUT BANS (scan + reject) ---
"""
    banned = " · ".join(lyra.get("banned_output_phrases", []))
    mc = load_entry_lm_model()
    footer = f"""
--- LM STUDIO ---
Model: {mc['lms_load_name']} @ http://127.0.0.1:1234/v1 ({mc['variant']} · minimal RLHF)
Conversation: Compile Layer（Entry B） id {mc['entry_b_conv']}
Daily 9B tab (qwen/qwen3.5-9b) is separate — do not unload or merge with this entry.
"""
    return HEADER + format_entry_b_lyra_syncon() + "\n\n" + tail + banned + footer


def main() -> None:
    text = build()
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT} ({len(text)} chars)")


if __name__ == "__main__":
    main()
