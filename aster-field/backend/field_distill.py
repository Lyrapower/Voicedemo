"""Re-export shared field_lane distill (8790 ↔ app same line)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "grid-sovereign-runtime"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from field_lane.distill import (  # noqa: E402
    archive_turn,
    distill_turn,
    emit_event,
    enabled as _enabled,
    schedule_after_turn,
    schedule_coach,
    should_distill,
)

__all__ = [
    "archive_turn",
    "distill_turn",
    "emit_event",
    "_enabled",
    "schedule_after_turn",
    "schedule_coach",
    "should_distill",
]
