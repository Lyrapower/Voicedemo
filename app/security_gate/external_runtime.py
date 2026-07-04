from __future__ import annotations
import os
import subprocess
from pathlib import Path
from typing import Optional

RUN_LOG = Path("logs/external_runtime.log")

def _log(line: str):
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def run_external_adapter(module: str, args: Optional[list] = None, venv_path: str = ".venv_external") -> subprocess.Popen:
    """
    Runs an external adapter in a separate python process, using a dedicated venv.
    Main process MUST NOT read API keys.
    """
    args = args or []

    # Hard rule: deny if key envs are present in parent process
    forbidden = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DASHSCOPE_API_KEY"]
    leaking = [k for k in forbidden if os.getenv(k)]
    if leaking:
        raise RuntimeError(f"SECURITY_FAIL: keys present in main process env: {leaking}")

    py = Path(venv_path) / "bin" / "python"
    if not py.exists():
        raise RuntimeError(f"Missing external venv python: {py}. Create venv_external before running adapters.")

    cmd = [str(py), "-m", module] + args
    _log("RUN " + " ".join(cmd))
    # Child process will be provided env separately by operator (not here).
    return subprocess.Popen(cmd, env={})
