"""Stage 3 — CC CLI Fable structural judge (numbers forbidden in output)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from offpool_coach import config as cfg
from offpool_coach.schema import Payload

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "offpool_coach_v1.txt"


def load_system_prompt() -> str:
    if PROMPT_PATH.is_file():
        return PROMPT_PATH.read_text(encoding="utf-8").strip()
    return (
        "你是 Fable 结构裁判。只评判 payload 中已有数据，禁止输出 payload 中不存在的数字。"
        "输出 strict JSON 数组，每 candidate 一条，含 grade/scores/thesis/falsifier/node_inferred。"
    )


def call_fable(payload: Payload) -> tuple[str, dict[str, Any]]:
    if cfg.RISK_BUDGET_USD is None:
        raise ValueError("RISK_BUDGET_USD unset — stage3 refused per spec §4")

    user = json.dumps(payload, ensure_ascii=False, indent=2)
    prompt = f"{load_system_prompt()}\n\n--- PAYLOAD ---\n{user}"

    import sys

    repo = Path(__file__).resolve().parents[2]
    v5 = repo / "aster_grid_v5"
    if str(v5) not in sys.path:
        sys.path.insert(0, str(v5))
    from distill.distill_cc_cli import coach_capture, default_coach_lane

    lane = default_coach_lane()
    lane = type(lane)(cli_model=cfg.FABLE_CLI_MODEL, label="offpool-coach")
    text, meta = coach_capture(prompt, lane)
    return text, meta
