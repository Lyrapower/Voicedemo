#!/usr/bin/env python3
"""Phase-4 oneshot gate. Default: isolated unit tests. --live is explicit production smoke."""
from __future__ import annotations
import argparse, os, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "harness_resident"
LOCK = Path(tempfile.gettempdir()) / "verify_phase4_oneshot.lock"


def _run(cmd: list[str], cwd: Path) -> int:
    print("+", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(cwd))
    print("exit", p.returncode, flush=True)
    return p.returncode


def unit_suite() -> int:
    tests = [
        (HARNESS / "harness", ["python3", "-m", "unittest", "test_compile_confirm", "test_task_schedule", "-v"]),
        (HARNESS / "harness", ["python3", "-m", "unittest", "test_safe_export", "-v"]),
        (ROOT / "scripts", ["python3", "test_provision_grid_store_token.py", "-v"]),
    ]
    rc = 0
    for cwd, cmd in tests:
        n = _run(cmd, cwd)
        if n:
            rc = n
    return rc


def live_smoke() -> int:
    """Read-only live probes. Does not create jobs or write store/diary."""
    import json, urllib.error, urllib.request
    tok_path = ROOT / "grid-sovereign-runtime" / "config" / "grid_store.token"
    if not tok_path.is_file():
        print("LIVE FAIL token file missing", flush=True)
        return 78
    tok = tok_path.read_text(encoding="utf-8").strip()
    req = urllib.request.Request("http://127.0.0.1:8501/health")
    with urllib.request.urlopen(req, timeout=8) as r:
        health = json.loads(r.read().decode())
    auth = (health.get("store_auth") or health.get("store") or "")
    print("health_ok", health.get("ok") or health.get("status") or True, "store_auth", auth)
    bad = urllib.request.Request(
        "http://127.0.0.1:8501/grid/compile/register",
        data=b'{"goal":"x","session_id":"compile"}',
        headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8501"},
        method="POST",
    )
    try:
        urllib.request.urlopen(bad, timeout=8)
        print("LIVE FAIL unauth register not rejected")
        return 1
    except urllib.error.HTTPError as e:
        print("unauth_register", e.code)
        if e.code != 401:
            return 1
    html = urllib.request.Request("http://127.0.0.1:8501/app/grid.html", method="HEAD")
    with urllib.request.urlopen(html, timeout=8) as r:
        cc = r.headers.get("Cache-Control") or ""
        print("grid_html_cache", cc)
        if "no-store" not in cc.lower():
            return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    fd = os.open(str(LOCK), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("locked", LOCK)
        return 75
    t0 = time.time()
    try:
        rc = unit_suite()
        if rc:
            return rc
        if args.live:
            rc = live_smoke()
        print("elapsed_s", round(time.time() - t0, 2))
        return rc
    finally:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
