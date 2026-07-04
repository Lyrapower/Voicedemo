"""Single source for compile LM Studio model — reads config/aster.toml."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "models"))

from aster_config import compile_model_id, load_aster_config  # noqa: E402


def load_compile_model() -> dict:
    cfg = load_aster_config()
    compile_cfg = cfg.get("models", {}).get("compile", {})
    return {
        "lms_load_name": compile_cfg.get("id", compile_model_id()),
        "lm_studio_conv": compile_cfg.get("conversation_id", "17797865158102"),
        "context_length": compile_cfg.get("context_length", 8192),
        "variant": "base",
    }


def load_entry_lm_model() -> dict:
    return load_compile_model()


def lms_model_name() -> str:
    return compile_model_id()
