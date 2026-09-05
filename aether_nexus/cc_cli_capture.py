"""Shared CC CLI read-only capture — uses code_task envelope."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from code_task import CodeTaskRequest, execute_cc_cli  # noqa: E402


@dataclass(frozen=True)
class CliLane:
    cli_model: str
    label: str = ""


def claude_capture(
    prompt: str,
    lane: CliLane,
    *,
    timeout: int | None = None,
) -> tuple[str, dict[str, Any]]:
    req = CodeTaskRequest(
        route_id="cc_cli",
        route_class="task",
        prompt=prompt,
        cli_model=lane.cli_model,
        cli_label=lane.label,
        timeout=float(timeout or 180),
    )
    resp = execute_cc_cli(req, cli_model=lane.cli_model, label=lane.label)
    return resp.text, resp.to_meta_dict()
