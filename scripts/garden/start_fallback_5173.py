#!/usr/bin/env python3
"""Free :5173 then exec Garden fallback runtime (launchd-friendly)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PORT = 5173

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.garden.port_free import free_port  # noqa: E402


def uvicorn_bin() -> str:
    system = "/Library/Frameworks/Python.framework/Versions/3.13/bin/uvicorn"
    if os.path.isfile(system) and os.access(system, os.X_OK):
        return system
    venv = os.path.join(ROOT, ".venv", "bin", "uvicorn")
    if os.path.isfile(venv) and os.access(venv, os.X_OK):
        return venv
    return "uvicorn"


def main() -> None:
    stale = free_port(PORT)
    if stale:
        print(f"garden5173: cleared stale listener(s) on :{PORT}: {', '.join(stale)}", file=sys.stderr)
    os.chdir(ROOT)
    uvicorn = uvicorn_bin()
    os.execvp(
        uvicorn,
        [
            uvicorn,
            "scripts.sound_lab_fallback:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--workers",
            "1",
        ],
    )


if __name__ == "__main__":
    main()
