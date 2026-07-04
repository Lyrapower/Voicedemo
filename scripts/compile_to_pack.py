#!/usr/bin/env python3
from __future__ import annotations
import json, re
from pathlib import Path

SRC = Path("knowledge/compiled/EXECUTION_PACK.md")
DST = Path("deliver/rounds/latest_pack.json")

def must(pattern: str, text: str, label: str) -> str:
    m = re.search(pattern, text, flags=re.MULTILINE)
    if not m:
        raise SystemExit(f"FAIL: missing {label}")
    return m.group(1).strip()

def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"FAIL: missing {SRC}")
    md = SRC.read_text(encoding="utf-8")

    round_id = must(r"^ROUND_ID:\s*(.+)$", md, "ROUND_ID")
    cmds_block = must(r"^## COMMANDS\s*\n([\s\S]+)$", md, "## COMMANDS")

    commands = []
    for line in cmds_block.splitlines():
        s = line.strip()
        if s.startswith("- "):
            commands.append(s[2:].strip())

    if not commands:
        raise SystemExit("FAIL: COMMANDS empty")

    DST.parent.mkdir(parents=True, exist_ok=True)
    payload = {"round_id": round_id, "commands": commands}
    DST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: wrote {DST}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
