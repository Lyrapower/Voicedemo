#!/usr/bin/env python3
"""Wait for Garden runtime on 5173, then exec Aster on 8787 (launchd-friendly)."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPO = os.path.join(ROOT, "repo")
PORT_RUNTIME = 5173
PORT_ASTER = 8787
WAIT_SEC = int(os.environ.get("GARDEN_WAIT_5173_SEC", "90"))


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def uvicorn_bin() -> str:
    system = "/Library/Frameworks/Python.framework/Versions/3.13/bin/uvicorn"
    if os.path.isfile(system) and os.access(system, os.X_OK):
        return system
    venv = os.path.join(ROOT, ".venv", "bin", "uvicorn")
    if os.path.isfile(venv) and os.access(venv, os.X_OK):
        return venv
    return "uvicorn"


def main() -> None:
    for _ in range(WAIT_SEC):
        if port_open(PORT_RUNTIME):
            break
        time.sleep(1)
    else:
        print(f"garden8787: timed out waiting for {PORT_RUNTIME}", file=sys.stderr)
        raise SystemExit(1)

    uvicorn = uvicorn_bin()
    os.chdir(REPO)
    os.execvp(uvicorn, [uvicorn, "app.main:app", "--host", "127.0.0.1", "--port", str(PORT_ASTER), "--workers", "1"])


if __name__ == "__main__":
    main()
