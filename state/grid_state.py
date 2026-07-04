from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict


STATE_PATH = Path("state/grid_context.json")
_lock = threading.Lock()


def _ensure_state_file() -> None:
    if not STATE_PATH.parent.exists():
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        with STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump({"last_intent_hash": None, "session_duration": 0.0}, f)


def read_state() -> Dict[str, Any]:
    with _lock:
        _ensure_state_file()
        with STATE_PATH.open("r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {"last_intent_hash": None, "session_duration": 0.0}
        return data


def write_state(last_intent_hash: int | str, session_duration: float) -> None:
    with _lock:
        _ensure_state_file()
        state: Dict[str, Any] = {
            "last_intent_hash": last_intent_hash,
            "session_duration": float(session_duration),
        }
        with STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(state, f)

