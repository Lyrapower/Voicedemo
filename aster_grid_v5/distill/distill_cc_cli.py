"""CC CLI coach capture for distill harness — code_task envelope, no :8503."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code_task import CodeTaskRequest, execute_cc_cli  # noqa: E402


@dataclass(frozen=True)
class CoachLane:
    cli_model: str
    label: str = "Fable distill coach"


def default_coach_lane() -> CoachLane:
    return CoachLane(
        cli_model=os.getenv("DISTILL_CLI_MODEL", os.getenv("TEACHER_MODEL", "claude-fable-5")),
        label=os.getenv("DISTILL_CLI_LABEL", "Fable · distill coach"),
    )


def coach_capture(
    prompt: str,
    lane: CoachLane | None = None,
    *,
    timeout: int | None = None,
) -> tuple[str, dict[str, Any]]:
    lane = lane or default_coach_lane()
    timeout = timeout or int(os.getenv("DISTILL_CLI_TIMEOUT", os.getenv("TEACHER_TIMEOUT", "180")))
    req = CodeTaskRequest(
        route_id="distill_coach",
        route_class="task",
        prompt=prompt,
        cli_model=lane.cli_model,
        cli_label=lane.label,
        timeout=float(timeout),
    )
    resp = execute_cc_cli(req, cli_model=lane.cli_model, label=lane.label)
    meta = resp.to_meta_dict()
    if resp.error:
        meta["error"] = resp.error
    return resp.text, meta
