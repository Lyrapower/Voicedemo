"""CC sandbox / dispatch watchdog timeout. Not hardcoded at call sites."""
from __future__ import annotations

import os
from typing import Any

# J-764a8177371d wall 121.02s → max(300, 3×121) = 363
DEFAULT_CC_SANDBOX_TIMEOUT_S = 363


def sandbox_timeout_s(cfg: Any | None = None) -> int:
    raw = os.getenv("CC_SANDBOX_TIMEOUT_S")
    if raw not in (None, ""):
        return max(1, int(float(raw)))
    if cfg is not None:
        v = getattr(getattr(cfg, "cc", None), "sandbox_timeout_s", None)
        if v is not None:
            return max(1, int(v))
    return DEFAULT_CC_SANDBOX_TIMEOUT_S
