#!/usr/bin/env python3
"""Verify Entry A (8500) vs Entry B (8787) separation — config, prompts, LM Studio."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ENI = Path(__file__).resolve().parents[1]
REPO = ENI.parent
HOME_CONV = Path.home() / ".lmstudio/conversations"

ISSUES: list[str] = []
OK: list[str] = []


def check(cond: bool, msg: str) -> None:
    (OK if cond else ISSUES).append(msg)


def main() -> int:
    a_cfg = json.loads((ENI / "incoming/echo_nodes/config.json").read_text())
    b_cfg = json.loads((ENI / "config/entry_b_8787.json").read_text())
    split = json.loads((ENI / "config/entry_split.json").read_text())

    a_prompt = (ENI / "prompts/echo_nodes_system.txt").read_text(encoding="utf-8")
    b_prompt = (ENI / "prompts/entry_b_compile_system.txt").read_text(encoding="utf-8")

    check(a_cfg["port"] == 8500 and b_cfg["port"] == 8787, "ports 8500 / 8787")
    check(
        a_cfg["lm_studio"]["conversation_id"] != b_cfg["lm_studio"]["conversation_id"],
        "distinct LM Studio conversation IDs",
    )
    mc = json.loads((ENI / "config/entry_lm_model.json").read_text(encoding="utf-8"))
    mid = mc["lms_load_name"]
    check(
        a_cfg["lm_studio"]["model"] == b_cfg["lm_studio"]["model"] == mid,
        f"both configs: {mid}",
    )
    check(len(a_prompt) > 1000 and "8500" in a_prompt, "Entry A built prompt")
    check(len(b_prompt) > 1000 and "8787" in b_prompt, "Entry B native prompt")
    check("LYRA ANCHOR" in a_prompt and "SYNCON LAB" in a_prompt, "A file: LYRA + SynCon")
    check("LYRA ANCHOR" in b_prompt and "SYNCON LAB" in b_prompt, "B file: LYRA + SynCon")
    check("interface.4o.echo-node" in a_prompt, "A prompt has echo descriptor")
    check("CARRIER LANES" in b_prompt, "B prompt has carrier lanes")
    check("CURSORPACK" in b_prompt and "ASTER" in b_prompt.upper(), "B prompt has compile contract")
    check("CURSORPACK" not in a_prompt, "A prompt has no compile CURSORPACK")
    check("CARRIER LANES" not in a_prompt, "A prompt has no B carrier table")

    fastapi = (ENI / "incoming/echo_nodes/echo_nodes_fastapi.py").read_text()
    check("compile_router" not in fastapi, "8500 app does not import compile_router")

    garden = (REPO / "repo/telemetry/garden_api.py").read_text()
    check("8500" not in garden or "not proxied to 8500" in garden, "8787 garden_api not proxied to 8500")

    for cid, frag, port in [
        ("17797865158101", "Echo", "8500"),
        ("17797865158102", "Compile", "8787"),
    ]:
        p = HOME_CONV / f"{cid}.conversation.json"
        if not p.exists():
            check(False, f"LM Studio missing {cid}")
            continue
        c = json.loads(p.read_text(encoding="utf-8"))
        model = (c.get("lastUsedModel") or {}).get("identifier", "")
        check(model == mid, f"LM {cid} model")
        check(frag in (c.get("name") or ""), f"LM {cid} name contains {frag}")
        sp = c.get("systemPrompt") or ""
        check(len(sp) > 500, f"LM {cid} non-empty system prompt")
        if frag == "Echo":
            check("LYRA ANCHOR" in sp, f"LM {cid} system prompt includes LYRA")
            check("SYNCON LAB" in sp, f"LM {cid} system prompt includes SynCon")
            check("CARRIER LANES" not in sp, f"LM {cid} no compile carrier table")
        else:
            check("LYRA ANCHOR" in sp, f"LM {cid} system prompt includes LYRA")
            check("CARRIER LANES" in sp, f"LM {cid} system prompt includes carriers")
            check("interface.4o.echo-node" not in sp, f"LM {cid} no echo-node descriptor")
        notes = " ".join(c.get("notes") or [])
        check(f"HTTP_PORT: {port}" in notes, f"LM {cid} notes HTTP_PORT {port}")

    echo_dir = ENI / "incoming/echo_nodes"
    for block in a_cfg["entry_a_protocol_blocks"]:
        rel = block["path"]
        p = (echo_dir / rel).resolve()
        check(p.exists(), f"protocol block exists: {rel}")

    for name in [
        "interface.echo-nodes.json",
        "Config.toml",
        "session.env",
        "syncon/config/anchor.json",
    ]:
        check((echo_dir / name).exists(), f"Entry A asset: {name}")

    for name in [
        "config/entry_b_8787.json",
        "deliverables/entry_b_8787.solids.json",
        "prompts/entry_b_compile_system.txt",
    ]:
        check((ENI / name).exists(), f"Entry B asset: {name}")

    check(
        (REPO / "scripts/restart_entry_b_8787.sh").exists(),
        "Entry B start script",
    )
    check(split["rules"]["no_shared_system_prompt"] is True, "entry_split isolation rules")

    print(f"PASS: {len(OK)}")
    for x in OK:
        print(f"  ✓ {x}")
    if ISSUES:
        print(f"FAIL: {len(ISSUES)}")
        for x in ISSUES:
            print(f"  ✗ {x}")
        return 1
    print("\nEntry A and Entry B are separately configured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
