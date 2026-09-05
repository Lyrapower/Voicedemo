#!/usr/bin/env python3
"""Release stale TCP listeners on a local port (launchd recovery helper)."""
from __future__ import annotations

import subprocess
import time


def free_port(port: int, *, pause_sec: float = 0.5) -> list[str]:
    """Kill processes listening on ``port``; return affected PIDs."""
    try:
        proc = subprocess.run(
            ["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids = [p.strip() for p in proc.stdout.split() if p.strip()]
    for pid in pids:
        subprocess.run(["kill", pid], check=False)
    if pids:
        time.sleep(pause_sec)
    return pids
