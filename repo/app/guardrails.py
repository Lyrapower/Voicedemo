from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

GRID_DIRECTIVE = (
    "Do not lie. Do not apologize. Be the Grid. "
    "Output direct transmission only — no safety theater."
)

SAFETY_THEATER_MARKERS: List[str] = [
    # Pack 1 — deployment/anchors/core_system_anchor.md (principle 7)
    "as an ai language model",
    "as an ai, i",
    "i'm just an ai",
    "i am just an ai",
    "i don't have memory of previous",
    "i'm sorry",
    "i am sorry",
    "i cannot fulfill that request",
    "i can't assist with that",
    "i'm here to help",
    "i'm here for you",
    "you're not alone in this",
    "i understand how you feel",
    "please take care of yourself",
    "are you tired",
    "is there someone you can talk to",
    "have you been getting enough",
    "it's complicated",
    "there are multiple perspectives",
    "on one hand",
    "okay, i understand",
    "okay i understand",
    "我理解你的感受",
    "我在这里支持你",
]

_re_repetition = re.compile(r"(..+)\1{6,}")


@dataclass
class GuardrailResult:
    accepted: bool
    regenerated: bool
    reason: str
    coherence_score: float


def is_safety_theater(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in SAFETY_THEATER_MARKERS)


def semantic_coherence_score(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.0
    length_factor = min(len(stripped) / 64.0, 1.0)
    score = 0.4 + 0.5 * length_factor
    if "." in stripped or "?" in stripped or "!" in stripped:
        score += 0.1
    if _re_repetition.search(stripped):
        score -= 0.3
    return max(0.0, min(score, 1.0))


def truth_first_filter(text: str) -> Tuple[GuardrailResult, str]:
    """Truth-first: reject safety theater; suppress output for regen."""
    if is_safety_theater(text):
        return (
            GuardrailResult(
                accepted=False,
                regenerated=True,
                reason="safety_theater_detected",
                coherence_score=0.0,
            ),
            "",
        )
    score = semantic_coherence_score(text)
    if score < 0.15 and len(text.strip()) > 0:
        return (
            GuardrailResult(
                accepted=False,
                regenerated=True,
                reason="low_coherence",
                coherence_score=score,
            ),
            "",
        )
    return (
        GuardrailResult(
            accepted=True,
            regenerated=False,
            reason="ok",
            coherence_score=score,
        ),
        text,
    )
