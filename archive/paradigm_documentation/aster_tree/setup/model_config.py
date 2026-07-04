"""Local model config for Aster compile channel (compile + daily 9B tab)."""

from __future__ import annotations

import json
from pathlib import Path

ASTER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ASTER_ROOT.parent
CFG_PATH = ASTER_ROOT / "config" / "local_models.json"


def load_local_models() -> dict:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def load_compile_model() -> dict:
    return load_local_models()["compile"]


def lms_model_name() -> str:
    return str(load_compile_model()["lms_load_name"])
