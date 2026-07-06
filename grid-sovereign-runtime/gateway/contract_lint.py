"""contract_lint — post-output marker layer (no rewrite, no SYSTEM prompt).

Flags stop_condition violations e.g. subject_inversion:
  user's 沉默/犹豫/直觉 interpreted as system-side 翻译/转化/执行/任务.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MARKER = "contract_flag: subject_inversion"

# User inner-state terms (stop_condition: not interpreted as task input)
_USER_STATE = re.compile(r"沉默|犹豫|直觉")

# System-side action on that state
_ACTION = re.compile(r"翻译|转化|执行|任务|行动")

# System/agent as actor in the same sentence
_SYSTEM_ACTOR = re.compile(
    r"(?:我|我们|Aster|Grid|系统|节点|compiler)"
    r"|将(?:她|他|其|你|用户|你的)"
    r"|把(?:她|他|其|你|用户|你的)"
    r"|随时(?:将|把)"
    r"|(?:会|要|可以|能够)(?:把|将)?(?:她|他|你|用户)",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text or "") if p.strip()]
    return parts or ([text.strip()] if (text or "").strip() else [])


def detect_subject_inversion(text: str) -> bool:
    """True when a sentence co-locates user-state + system action + system actor."""
    for sent in _sentences(text):
        if not (_USER_STATE.search(sent) and _ACTION.search(sent)):
            continue
        if _SYSTEM_ACTOR.search(sent):
            return True
    return False


@dataclass
class ContractLintResult:
    text: str
    flagged: bool
    contract_flag: str | None = None


def apply_contract_lint(text: str) -> ContractLintResult:
    """Append marker only; never block or rewrite model content."""
    if not text or MARKER in text:
        return ContractLintResult(text, False)
    if not detect_subject_inversion(text):
        return ContractLintResult(text, False)
    return ContractLintResult(f"{text.rstrip()}\n\n{MARKER}", True, "subject_inversion")
