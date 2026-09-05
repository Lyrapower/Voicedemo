"""E3 — drop Sonnet earnings output when facts are not grounded in prompt input."""
from __future__ import annotations

import re
from typing import Any


_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")


def _prompt_facts(prompt: str) -> set[str]:
    facts: set[str] = set()
    for m in _DATE_RE.finditer(prompt or ""):
        facts.add(m.group(1))
    for m in _NUM_RE.finditer(prompt or ""):
        facts.add(m.group(0))
    for sym in re.findall(r"\b[A-Z]{1,5}\b", prompt or ""):
        if len(sym) >= 2:
            facts.add(sym)
    return facts


def detect_confabulation(*, prompt: str, output: str) -> list[str]:
    """Return list of output tokens not traceable to prompt (dates/numbers/symbols)."""
    if not output.strip():
        return []
    allowed = _prompt_facts(prompt)
    hits: list[str] = []
    for m in _DATE_RE.finditer(output):
        if m.group(1) not in allowed:
            hits.append(f"date:{m.group(1)}")
    for sym in re.findall(r"标的：([A-Z]{1,5})", output):
        if sym not in allowed:
            hits.append(f"sym:{sym}")
    return hits


def validate_earnings_item(*, prompt: str, item: dict[str, Any]) -> tuple[bool, list[str]]:
    hits: list[str] = []
    # E-3: single-leg call only — long or skip; bearish/neutral is a constitution breach.
    value = str(item.get("value") or "")
    dir_i = int(item.get("dir") or 0)
    if "空" in value or dir_i < 0:
        hits.append("direction:bearish")
    elif dir_i != 1:
        hits.append(f"direction:not_long(dir={dir_i})")
    blob = "\n".join(str(item.get(k) or "") for k in ("sym", "reason", "risk", "note", "value"))
    hits.extend(detect_confabulation(prompt=prompt, output=blob))
    return (not hits, hits)
