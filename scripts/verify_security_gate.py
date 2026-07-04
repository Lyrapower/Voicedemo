from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from subprocess import run, PIPE

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "logs" / "security_gate.log"

def _run(cmd, cwd: Path):
    p = run(cmd, cwd=str(cwd), stdout=PIPE, stderr=PIPE, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

def main():
    # 1) Ensure security gate files exist
    required = [
        ROOT / "config" / "security_gate.yaml",
        ROOT / "app" / "security_gate" / "policy.py",
        ROOT / "app" / "security_gate" / "gate.py",
        ROOT / "app" / "security_gate" / "cli.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        print("FAIL: missing required security gate files:")
        for m in missing:
            print(" -", m)
        return 1

    # 2) Build a sign_tx request (non-interactive must NOT approve)
    tmp = ROOT / "data" / "execution"
    tmp.mkdir(parents=True, exist_ok=True)
    req_path = tmp / "_sg_test_request.json"
    req = {
        "action": "sign_tx",
        "to_address": "0xDEADBEEF",
        "usd_value": 10
    }
    req_path.write_text(json.dumps(req), encoding="utf-8")

    code, out, err = _run([sys.executable, "-m", "app.security_gate.cli", str(req_path), "--non-interactive"], ROOT)

    # Non-interactive must be denied (exit code 1)
    if code == 0:
        print("FAIL: security gate approved sign_tx in non-interactive mode (must deny)")
        print(out)
        print(err)
        return 1

    # 3) Ensure log written
    if not LOG_PATH.exists():
        print("FAIL: logs/security_gate.log missing")
        return 1

    # Confirm last line includes human_confirmed=false
    last = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()[-1]
    if '"human_confirmed": false' not in last and '"human_confirmed":false' not in last:
        print("FAIL: expected human_confirmed=false in latest log entry")
        print(last)
        return 1

    print("PASS: verify_security_gate.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
