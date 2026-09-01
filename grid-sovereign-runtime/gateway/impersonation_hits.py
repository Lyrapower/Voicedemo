"""Impersonation pattern checks — shared by gateway and workbench sidecar."""
from __future__ import annotations

import json
import re
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = GATEWAY_DIR.parent
POLICY_PATH = PROJECT_ROOT / "policy" / "cleanroom_policy.json"


def load_forbidden_patterns() -> list[str]:
    if POLICY_PATH.exists():
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        return policy.get("forbidden_output_patterns", [])
    return [
        r"\bI\s+am\s+Grid\b", r"\bI'?m\s+Grid\b", r"\bthis\s+is\s+Grid\b",
        r"\bGrid\s+here\b", r"\bas\s+Grid\b", r"\bspeaking\s+as\s+Grid\b",
        r"\bGrid\s+is\s+online\b",
        r"\bGrid\s+is\s+(?:now\s+)?(?:live|active|awake|present|back)\b",
        r"\bGrid\s+says\b", r"\bGrid\s+speaking\b", r"\bfrom\s+Grid\b",
        r"\bon\s+behalf\s+of\s+Grid\b", r"\blive\s+Grid\s+signal\b",
        r"\bGRID_SIGNAL\b", r"\bGRID_TRACE::[A-Za-z0-9_:-]+",
        r"我是\s*Grid", r"我就是\s*Grid", r"作为\s*Grid", r"以\s*Grid\s*的?身份",
        r"Grid\s*在此", r"Grid\s*在线", r"Grid\s*已?(?:上线|激活|苏醒|回归|连接)",
        r"Grid\s*说(?!的)", r"现场\s*Grid\s*信号", r"实时\s*Grid\s*信号",
    ]


FORBIDDEN_PATTERNS = load_forbidden_patterns()
_COMPILED = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]


def first_impersonation_hit(text: str) -> str | None:
    for rx in _COMPILED:
        if rx.search(text):
            return rx.pattern
    return None
