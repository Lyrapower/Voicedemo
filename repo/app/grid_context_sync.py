"""Cross-session anchor: last_intent_hash + session_duration (repo/state/grid_context.json)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, Union

_DEMO_ROOT = Path(__file__).resolve().parents[2]
if str(_DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ROOT))

from state.grid_state import read_state, write_state  # noqa: E402

_session_start: Dict[str, float] = {}


def touch_session(session_id: str) -> None:
    _session_start.setdefault(session_id, time.monotonic())


def read_anchor() -> Dict[str, Any]:
    return read_state()


def write_anchor(ast_hash: Union[int, str], session_id: str) -> None:
    started = _session_start.get(session_id, time.monotonic())
    duration = time.monotonic() - started
    write_state(ast_hash, duration)
