"""Parse merged model output as JSON artifact — never treat half-JSON as PASS."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "grid-sovereign-runtime"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from field_lane.schema import SCHEMA_LOOSE, COMPILE_SEMANTICS_PARSE_ONLY  # noqa: E402


def _strip_fences(text: str) -> str:
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    return m.group(1).strip() if m else text.strip()


def _slice_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text.strip()


def parse_json_artifact(raw: str) -> dict:
    text = _strip_fences(raw)
    last_err = "empty"
    for candidate in (text, _slice_object(text)):
        if not candidate:
            continue
        try:
            return {
                "ok": True,
                "json": json.loads(candidate),
                "merged_json_valid": True,
                "schema": SCHEMA_LOOSE,
                "compile_semantics": COMPILE_SEMANTICS_PARSE_ONLY,
            }
        except json.JSONDecodeError as e:
            last_err = str(e)
    return {
        "ok": False,
        "status": "INCOMPLETE_ARTIFACT",
        "merged_json_valid": False,
        "schema": SCHEMA_LOOSE,
        "compile_semantics": COMPILE_SEMANTICS_PARSE_ONLY,
        "error": last_err,
    }
