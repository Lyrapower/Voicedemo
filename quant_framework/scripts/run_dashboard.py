#!/usr/bin/env python
"""Launch Streamlit dashboard on port 8501."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "quant_framework" / "dashboard" / "app.py"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


def _python() -> str:
    """Prefer project venv so streamlit + quant_framework are available."""
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def main() -> None:
    port = os.environ.get("DASHBOARD_PORT", "8501")
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args):
            port = args[i + 1]

    if not APP.is_file():
        print(f"ERROR: Dashboard app not found: {APP}", file=sys.stderr)
        sys.exit(1)

    py = _python()
    print(f"Starting dashboard at http://localhost:{port}")
    print(f"Python: {py}")
    print("Press Ctrl+C to stop.\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            py,
            "-m",
            "streamlit",
            "run",
            str(APP),
            "--server.port",
            port,
            "--server.address",
            "localhost",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=str(ROOT),
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
