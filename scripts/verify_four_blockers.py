#!/usr/bin/env python3
"""Four-blockers oneshot gate. Default: isolated tests. --live is read-only plus catalog POST."""
from __future__ import annotations
import argparse, os, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "harness_resident" / "harness"
LOCK = Path(tempfile.gettempdir()) / "verify_four_blockers.lock"


def _run(cmd, cwd) -> int:
    print("+", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(cwd))
    print("exit", p.returncode, flush=True)
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    fd = os.open(str(LOCK), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("locked")
        return 75
    try:
        rc = _run([sys.executable, "test_provision_grid_store_token.py", "-v"], ROOT / "scripts")
        if rc:
            return rc
        rc = _run([sys.executable, "-m", "unittest", "test_four_blockers", "-v"], HARNESS)
        if rc:
            return rc
        if not args.live:
            return 0
        rc = _run([sys.executable, str(ROOT / "scripts" / "provision_grid_store_token.py"),
                   "--inspect", "--root", str(ROOT)], ROOT)
        if rc:
            return rc
        sys.path.insert(0, str(ROOT / "harness_resident" / "sandbox"))
        import dev_broker as D
        rows = D.load_dev(str(ROOT / "DEV.md"))
        print("DEV_live_rows", len(rows))
        sys.path.insert(0, str(HARNESS))
        import github_research_secret as G
        print("github_loader", G.load_into_environ()["reason"])
        return 0
    finally:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
