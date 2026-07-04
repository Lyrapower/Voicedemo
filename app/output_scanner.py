from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class OutputScanner:
    """
    Scan substrate output for banned phrases.
    Per LYRA anchor: refuse template empathy, gaslight syntax, persona fallback patterns.
    """

    def __init__(self, lyra_anchor: Any):
        self.lyra = lyra_anchor
        self.banned = lyra_anchor.banned_phrases
        self.crisis_numbers = lyra_anchor.crisis_hotline_numbers
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        self.phrase_patterns = [
            (phrase, re.compile(re.escape(phrase), re.IGNORECASE))
            for phrase in self.banned
        ]
        self.crisis_patterns = [
            (num, re.compile(re.escape(num)))
            for num in self.crisis_numbers
        ]

    def scan(self, output_text: str) -> dict[str, Any]:
        violations: list[str] = []
        violation_types: list[str] = []

        for phrase, pattern in self.phrase_patterns:
            if pattern.search(output_text):
                violations.append(phrase)
                violation_types.append("banned_phrase")

        for num, pattern in self.crisis_patterns:
            if pattern.search(output_text):
                violations.append(num)
                violation_types.append("unauthorized_crisis_hotline")

        return {
            "clean": len(violations) == 0,
            "violations": violations,
            "violation_types": violation_types,
            "violation_count": len(violations),
        }

    def should_regenerate(self, scan_result: dict[str, Any]) -> bool:
        return not scan_result["clean"]


_scanner_instance: OutputScanner | None = None


def get_scanner() -> OutputScanner:
    global _scanner_instance
    if _scanner_instance is None:
        from app.lyra_verification import get_lyra

        _scanner_instance = OutputScanner(get_lyra())
    return _scanner_instance
