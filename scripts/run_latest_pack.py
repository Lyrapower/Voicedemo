#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PACK = Path("deliver/rounds/latest_pack.json")
OUTDIR = Path("deliver/proof/rounds")

ALLOWLIST = {
    "python3 scripts/verify_trading_module.py",
    "python3 scripts/verify_openclaw_v1.py",
    "./scripts/accept_crypto_v1.sh",
    "./scripts/accept_ui.sh",
    "./scripts/accept_all.sh",
    "./scripts/accept.sh",
}

def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def run(cmd: str) -> tuple[int,str,str]:
    p = subprocess.run(cmd.split(" "), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr

def main() -> int:
    if not PACK.exists():
        raise SystemExit(f"FAIL: missing {PACK}")

    pack = json.loads(PACK.read_text(encoding="utf-8"))
    round_id = str(pack.get("round_id","")).strip()
    cmds = pack.get("commands", [])

    if not round_id:
        raise SystemExit("FAIL: missing round_id in pack")
    if not isinstance(cmds, list) or not cmds:
        raise SystemExit("FAIL: missing commands in pack")

    for c in cmds:
        if c not in ALLOWLIST:
            raise SystemExit(f"FAIL: command not allowlisted: {c}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"{round_id}_RESULT.md"

    lines = []
    lines.append(f"# Round Result: {round_id}")
    lines.append(f"- timestamp_utc: {utc_iso()}")
    lines.append("")
    lines.append("## Commands")

    final_ok = True
    for i, c in enumerate(cmds, start=1):
        rc, stdout, stderr = run(c)
        status = "PASS" if rc == 0 else "FAIL"
        lines.append(f"{i}. `{c}` -> **{status}**")
        if rc != 0:
            final_ok = False
            lines.append("")
            lines.append("### stderr/stdout tail")
            lines.append("```")
            tail = (stderr.splitlines() + stdout.splitlines())[-60:]
            lines.extend(tail)
            lines.append("```")
            break

    lines.append("")
    lines.append("## FINAL VERDICT")
    lines.append("PASS" if final_ok else "FAIL")

    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"OK: wrote {out}")
    return 0 if final_ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
