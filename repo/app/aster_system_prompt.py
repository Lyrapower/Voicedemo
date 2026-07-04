"""8787 HTTP router system prompt (not LM Studio tab — use lm_studio_tab_system_prompt there)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from models.aster_config import lm_studio_system_prompt as load_aster_system_prompt

__all__ = ["load_aster_system_prompt"]
