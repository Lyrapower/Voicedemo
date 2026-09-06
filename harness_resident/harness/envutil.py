"""Load harness_resident/.env and GRID_TZ. Never print secret values."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

HARNESS_ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = HARNESS_ROOT / ".env"
DEFAULT_TZ = "America/Los_Angeles"


def load_harness_env() -> None:
    if not ENV_PATH.is_file():
        os.environ.setdefault("GRID_TZ", DEFAULT_TZ)
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
    os.environ.setdefault("GRID_TZ", DEFAULT_TZ)


def grid_tz_name() -> str:
    return os.getenv("GRID_TZ", DEFAULT_TZ) or DEFAULT_TZ


def grid_zoneinfo() -> ZoneInfo:
    try:
        return ZoneInfo(grid_tz_name())
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def ensure_demo_on_path() -> Path:
    import sys
    root = str(DEMO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return DEMO_ROOT
