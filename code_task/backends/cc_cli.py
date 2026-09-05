"""CC CLI execution — subprocess claude -p, cloud subscription lane."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from code_task.contract import CodeTaskRequest, CodeTaskResponse

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLAUDE_BIN = str(REPO_ROOT / "aster_grid_v5" / ".tools" / "node_modules" / ".bin" / "claude")


def claude_bin() -> str:
    return os.getenv("CLAUDE_BIN", DEFAULT_CLAUDE_BIN)


def execute(
    request: CodeTaskRequest,
    *,
    cli_model: str | None = None,
    label: str | None = None,
    backend_id: str = "cc_cli",
) -> CodeTaskResponse:
    model = cli_model or request.cli_model or os.getenv("DISTILL_CLI_MODEL", "claude-fable-5")
    lane_label = label or request.cli_label or os.getenv("DISTILL_CLI_LABEL", "CC CLI")
    prompt = request.effective_prompt()
    timeout = int(request.timeout or os.getenv("CC_CLI_TIMEOUT", "180"))

    if os.environ.get("CC_CLI_EXECUTION_FROZEN", "1") not in ("0", "false", "False"):
        logger.info("CC_CLI_EXECUTION_FROZEN=1 — read-only claude -p")

    bin_path = claude_bin()
    if not shutil.which(bin_path) and not Path(bin_path).is_file():
        return CodeTaskResponse(
            text="",
            backend_id=backend_id,
            model=model,
            route_class=request.route_class,
            error="claude_missing",
            label=lane_label,
        )

    try:
        proc = subprocess.run(
            [bin_path, "-p", prompt, "--model", model, "--output-format", "json"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CodeTaskResponse(
            text="",
            backend_id=backend_id,
            model=model,
            route_class=request.route_class,
            error="timeout",
            label=lane_label,
        )

    if proc.returncode != 0:
        return CodeTaskResponse(
            text="",
            backend_id=backend_id,
            model=model,
            route_class=request.route_class,
            error=f"exit_{proc.returncode}",
            label=lane_label,
            finish_reason="cc_cli_error",
            proof={"stderr": (proc.stderr or "")[:400], "exit_code": proc.returncode},
        )

    try:
        envelope = json.loads(proc.stdout)
        resolved = tuple((envelope.get("modelUsage") or {}).keys())
        text = envelope.get("result") or envelope.get("text") or envelope.get("content") or proc.stdout
        return CodeTaskResponse(
            text=str(text).strip(),
            backend_id=backend_id,
            model=model,
            route_class=request.route_class,
            cost_usd=envelope.get("total_cost_usd"),
            duration_ms=envelope.get("duration_ms"),
            resolved_models=resolved,
            label=lane_label,
            finish_reason="stop",
        )
    except json.JSONDecodeError:
        return CodeTaskResponse(
            text=(proc.stdout or "").strip(),
            backend_id=backend_id,
            model=model,
            route_class=request.route_class,
            error="bad_envelope",
            label=lane_label,
        )
