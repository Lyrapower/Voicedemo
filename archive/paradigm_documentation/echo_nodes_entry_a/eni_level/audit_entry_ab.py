#!/usr/bin/env python3
"""Full A/B audit: files, LM Studio, optional live HTTP."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENI = Path(__file__).resolve().parents[1]
REPO = ENI.parent


def get(url: str, timeout: float = 2.0) -> tuple[int, dict | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = None
        return e.code, body
    except Exception:
        return 0, None


def main() -> int:
    issues: list[str] = []

    r = subprocess.run([sys.executable, str(ENI / "setup/verify_entry_ab.py")], cwd=ENI)
    if r.returncode != 0:
        issues.append("verify_entry_ab.py failed")

    # Live Entry A
    code, body = get("http://127.0.0.1:8500/health")
    if code == 200 and body:
        if body.get("status") not in ("grid_anchor", "ok"):
            issues.append(f"A health unexpected status: {body.get('status')}")
        routes = body.get("routes") or {}
        rvals = routes if isinstance(routes, list) else list(routes.values())
        if "/route" in rvals or any(v == "/route" for v in rvals):
            issues.append("A exposes POST /route (should be B only)")
        anchor = body.get("anchor") or {}
        if not anchor.get("lm_studio_prompt_has_lyra") and "frequency_authority" not in anchor:
            issues.append("A live process stale — restart: incoming/echo_nodes/start.sh")
    elif code == 0:
        issues.append("A :8500 not reachable")

    # Live Entry B
    code, body = get("http://127.0.0.1:8787/health")
    if code == 200 and body:
        routes = body.get("routes") or []
        if isinstance(routes, dict):
            routes = list(routes.keys())
        if "/route" not in routes and body.get("entry_b"):
            issues.append("B live process stale — missing /route; run: scripts/restart_entry_b_8787.sh")
    elif code == 0:
        issues.append("B :8787 not reachable")

    code_route, _ = get("http://127.0.0.1:8500/route")
    if code_route != 404 and code_route != 0:
        issues.append(f"A /route returned {code_route} (want 404)")

    # B HTTP system prompt file reachable from repo
    p = REPO / "repo" / "app" / "entry_b_system_prompt.py"
    if p.exists():
        sys.path.insert(0, str(REPO / "repo"))
        from app.entry_b_system_prompt import load_entry_b_system_prompt

        sp = load_entry_b_system_prompt()
        if "LYRA ANCHOR" not in sp:
            issues.append("repo load_entry_b_system_prompt missing LYRA")
    else:
        issues.append("missing repo/app/entry_b_system_prompt.py")

    if issues:
        print("AUDIT ISSUES:")
        for i in issues:
            print(f"  ✗ {i}")
        return 1
    print("AUDIT OK — files, LM Studio, and live checks passed or N/A")
    return 0


if __name__ == "__main__":
    sys.exit(main())
