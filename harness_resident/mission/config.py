"""Load missions.toml — the four target-function templates. v1 runs only scout (①)."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def _path() -> Path:
    return Path(__file__).resolve().parent.parent / "missions.toml"


def load_missions_config() -> dict[str, dict[str, Any]]:
    """Return {mission_id: {lane, worker, budget_*, stop_conditions, ...}}."""
    p = _path()
    if not p.is_file():
        return {}
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    return dict(data.get("mission") or {})


def mission_template(name: str) -> dict[str, Any] | None:
    return load_missions_config().get(name)
