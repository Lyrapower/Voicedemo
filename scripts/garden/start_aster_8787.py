#!/usr/bin/env python3
"""Wait briefly for Garden runtime on 5173, then exec Aster on 8787 (launchd-friendly)."""
from __future__ import annotations

import os
import socket
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPO = os.path.join(ROOT, "repo")
PORT_RUNTIME = 5173
PORT_ASTER = 8787
WAIT_SEC = int(os.environ.get("GARDEN_WAIT_5173_SEC", "20"))
REQUIRE_5173 = os.environ.get("GARDEN_REQUIRE_5173", "0") == "1"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.garden.port_free import free_port  # noqa: E402


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
        msg = f"garden8787: port {PORT_RUNTIME} not up after {WAIT_SEC}s"
        if REQUIRE_5173:
            print(msg, file=sys.stderr)
            raise SystemExit(1)
        print(f"{msg}; starting :{PORT_ASTER} anyway (legacy UI needs :{PORT_RUNTIME})", file=sys.stderr)

    stale = free_port(PORT_ASTER)
    if stale:
        print(f"garden8787: cleared stale listener(s) on :{PORT_ASTER}: {', '.join(stale)}", file=sys.stderr)

    uvicorn = uvicorn_bin()
    os.chdir(REPO)
    os.execvp(
        uvicorn,
        [uvicorn, "app.main:app", "--host", "127.0.0.1", "--port", str(PORT_ASTER), "--workers", "1"],
    )


if __name__ == "__main__":
    main()
