from __future__ import annotations

import re
from dataclasses import dataclass


FILLER_PREFIXES = [
    "as an ai",
    "i'm sorry",
    "i am sorry",
    "okay, i understand",
    "okay i understand",
]


_re_ws = re.compile(r"\s+")
_re_repetition = re.compile(r"(..+)\1{6,}")


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason: str
    coherence_score: float


def coherence_score(text: str) -> float:
    t = text.strip()
    if not t:
        return 0.0
    score = 0.4
    if len(t) >= 12:
        score += 0.2
    if len(set(t)) > 6:
        score += 0.2
    if not _re_repetition.search(t):
        score += 0.2
    return max(0.0, min(score, 1.0))


def validate_plain_text(text: str) -> ValidationResult:
    t = text.strip()
    if not t:
        return ValidationResult(False, "empty_response", 0.0)

    lowered = _re_ws.sub(" ", t.lower())
    if any(lowered.startswith(p) for p in FILLER_PREFIXES):
        return ValidationResult(False, "generic_filler_prefix", 0.0)

    # reject obvious markdown wrappers unless caller asked (router controls that)
    if lowered.startswith("```") or lowered.startswith("# "):
        return ValidationResult(False, "markdown_wrapped", 0.0)

    return ValidationResult(True, "ok", coherence_score(t))

