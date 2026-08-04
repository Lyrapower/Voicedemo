"""Affect / negation / hard-boundary provenance for intent compilation.

Deterministic only. No LLM. Does not soften, reframe, or invent goals.
UNKNOWN when unsure — never guess into rejected_interpretations.
"""
from __future__ import annotations

import re
from typing import Any

UNKNOWN = "UNKNOWN"

# Explicit negation / prohibition — user-authored only (not compiler inference).
_NEGATION_RES = [
    # ZH
    re.compile(
        r"(?P<span>(?:绝对|坚决|千万)?(?:不要|不许|不准|禁止|杜绝|绝不能|不可以|别再)"
        r"[^。！？\n.!?]{0,80})"
    ),
    re.compile(r"(?P<span>不是\s*[^。！？\n.!?]{0,60})"),
    re.compile(r"(?P<span>别\s*(?:再)?[^。！？\n.!?]{0,60})"),
    # EN
    re.compile(
        r"(?P<span>(?:do\s+not|don't|never|must\s+not|cannot|can't|no\s+more)\s+"
        r"[^.\n!?]{0,80})",
        re.I,
    ),
    re.compile(
        r"(?P<span>(?:stop|quit)\s+(?:telling|assuming|reframing|softening|rewriting)\s+"
        r"[^.\n!?]{0,60})",
        re.I,
    ),
]

_HARD_BOUNDARY_RES = [
    re.compile(
        r"(?P<span>(?:红线|硬边界|不可重解释|不可协商|底线|铁律)"
        r"[^。！？\n.!?]{0,80})"
    ),
    re.compile(
        r"(?P<span>(?:hard\s*boundary|red\s*line|non[- ]negotiable|do\s+not\s+reinterpret)"
        r"[^.\n!?]{0,80})",
        re.I,
    ),
    re.compile(
        r"(?P<span>(?:必须|只能|务必)[^。！？\n.!?]{0,60})",
    ),
]

# Affect cue → type. Intensity derived from cue strength + local emphasis.
_AFFECT_CUES: list[tuple[str, re.Pattern[str], float]] = [
    ("anger", re.compile(r"(愤怒|生气|火大|受够了|烦死|气死|怒|愤怒地|怒了)", re.I), 0.85),
    ("anger", re.compile(r"\b(angry|furious|pissed|outrage|mad\s+at)\b", re.I), 0.8),
    ("frustration", re.compile(r"(烦透|折腾|又来|第\s*\d+\s*次|再三|反复说了)", re.I), 0.7),
    ("frustration", re.compile(r"\b(frustrat\w*|sick\s+of|enough\s+already|again\s+and\s+again)\b", re.I), 0.7),
    ("urgency", re.compile(r"(立刻|马上|赶紧|刻不容缓|现在就|紧急)", re.I), 0.75),
    ("urgency", re.compile(r"\b(urgent|immediately|right\s+now|asap|critical)\b", re.I), 0.75),
    ("emphasis", re.compile(r"(重点是|听清楚|我说的是|必须听懂|强调)", re.I), 0.65),
    ("emphasis", re.compile(r"\b(listen|i\s+said|pay\s+attention|emphasiz\w*)\b", re.I), 0.6),
]


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


# Polarity bomb fix: never emit a bare positive string as normalized_rule.
POLARITY_FORBIDDEN = "forbidden"
POLARITY_REQUIRED = "required"
_FORBIDDEN_PREFIX = "FORBIDDEN:"
_REQUIRED_PREFIX = "REQUIRED:"

# Per-clause negation: cue + body up to clause break (，、；。!?).
# Splits "禁止A，禁止B" into two FORBIDDEN items — no half-stripped polarity.
_CLAUSE_NEG_RE = re.compile(
    r"(?P<cue>(?:绝对|坚决|千万)?(?:不要|不许|不准|禁止|杜绝|绝不能|不可以|别再|别|不得|不是)|"
    r"(?:do\s+not|don't|never|must\s+not|cannot|can't|no\s+more))\s*"
    r"(?P<body>[^。！？\n.!?，,；;]+)",
    re.I,
)
_CLAUSE_REQ_RE = re.compile(
    r"(?P<cue>必须|只能|务必|must|shall)\s*"
    r"(?P<body>[^。！？\n.!?，,；;]+)",
    re.I,
)


def _span_target(span: str) -> str:
    """Object fragment for affect windows only — NOT for constraint rules."""
    s = span.strip()
    s2 = re.sub(
        r"^(?:绝对|坚决|千万)?(?:不要|不许|不准|禁止|杜绝|绝不能|不可以|别再|别|不是|不得)\s*",
        "",
        s,
    )
    s2 = re.sub(
        r"^(?:do\s+not|don't|never|must\s+not|cannot|can't|no\s+more)\s+",
        "",
        s2,
        flags=re.I,
    )
    s2 = s2.strip(" ：:，,")
    if len(s2) < 2:
        return UNKNOWN
    return s2[:120]


def format_polarized_rule(polarity: str, action: str) -> str:
    """Only legal string form of a constraint rule for any downstream."""
    body = (action or "").strip()
    if not body:
        body = UNKNOWN
    if polarity == POLARITY_REQUIRED:
        return _REQUIRED_PREFIX + body[:200]
    return _FORBIDDEN_PREFIX + body[:200]


def constraint_export(item: dict[str, Any]) -> str:
    """Downstream-safe export. Never returns bare positive action text."""
    rule = str(item.get("normalized_rule") or "")
    pol = str(item.get("polarity") or "")
    if rule.startswith(_FORBIDDEN_PREFIX) or rule.startswith(_REQUIRED_PREFIX):
        return rule
    if pol == POLARITY_REQUIRED:
        return format_polarized_rule(POLARITY_REQUIRED, rule)
    return format_polarized_rule(POLARITY_FORBIDDEN, rule)


def bare_rule_readable_as_positive(normalized_rule: str) -> bool:
    """True if rule can be misread as a positive instruction (polarity bomb)."""
    r = (normalized_rule or "").strip()
    if not r or r == UNKNOWN:
        return False
    if r.startswith(_FORBIDDEN_PREFIX) or r.startswith(_REQUIRED_PREFIX):
        return False
    # Leading negation cues = still polarized in-text
    if re.match(
        r"^(?:不要|不许|不准|禁止|杜绝|绝不能|不可以|别再|别|不得|不是|"
        r"do\s+not|don't|never|must\s+not|FORBIDDEN:|REQUIRED:)",
        r,
        re.I,
    ):
        return False
    return True


def _collect_spans(prompt: str, patterns: list[re.Pattern[str]]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for cre in patterns:
        for m in cre.finditer(prompt):
            span = (m.groupdict().get("span") or m.group(0) or "").strip()
            if not span or span in seen:
                continue
            seen.add(span)
            found.append(span)
    return found


def detect_repetition_phrases(prompt: str) -> list[tuple[str, int]]:
    """Return (phrase, count) for repeated tokens/short phrases (count>=2)."""
    text = prompt or ""
    counts: dict[str, int] = {}
    # Sliding CJK windows (3–8 chars) catch "说了三遍" style repeats
    cjk = re.findall(r"[\u4e00-\u9fff]+", text)
    for run in cjk:
        for n in (3, 4, 5, 6, 7, 8):
            if len(run) < n:
                continue
            for i in range(0, len(run) - n + 1):
                gram = run[i : i + n]
                counts[gram] = counts.get(gram, 0) + 1
    for t in re.findall(r"[A-Za-z]{3,24}", text):
        key = t.lower()
        counts[key] = counts.get(key, 0) + 1
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        counts[ln] = counts.get(ln, 0) + 1
    out: list[tuple[str, int]] = []
    for k, n in counts.items():
        # sliding windows overcount; require true substring occurrences ≥2
        occ = text.lower().count(k.lower()) if k.isascii() else text.count(k)
        if occ >= 2 and 2 <= len(k) <= 40:
            out.append((k, occ))
    # prefer longer phrases
    out.sort(key=lambda x: (-len(x[0]), -x[1]))
    # drop grams fully contained in a longer kept phrase with same count
    kept: list[tuple[str, int]] = []
    for phrase, n in out:
        if any(phrase != p and phrase in p and n <= m for p, m in kept):
            continue
        kept.append((phrase, n))
        if len(kept) >= 8:
            break
    return kept


def extract_affect_signals(prompt: str) -> list[dict[str, Any]]:
    """Structured affect_signals. No personality inference."""
    text = prompt or ""
    signals: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    bangs = len(re.findall(r"[!！]{2,}", text))
    caps_ratio = 0.0
    letters = [c for c in text if c.isalpha()]
    if letters:
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)

    for typ, cre, base in _AFFECT_CUES:
        for m in cre.finditer(text):
            phrase = m.group(0).strip()
            key = (typ, phrase)
            if key in seen:
                continue
            seen.add(key)
            intens = base
            if bangs:
                intens += min(0.15, 0.05 * bangs)
            if caps_ratio >= 0.55 and len(letters) >= 8:
                intens += 0.1
            # Sentence containing the cue only (no cross-sentence bleed).
            left = 0
            for sep in ("\n", "。", "！", "？", ".", "!", "?"):
                i = text.rfind(sep, 0, m.start())
                if i >= left:
                    left = i + 1
            right = len(text)
            for sep in ("\n", "。", "！", "？", ".", "!", "?"):
                i = text.find(sep, m.end())
                if i != -1 and i < right:
                    right = i
            clause = text[left:right].strip() or phrase
            # Prefer object after cue colon／： when present
            after = re.split(r"[：:]", clause, maxsplit=1)
            if len(after) == 2 and after[1].strip():
                target = after[1].strip()
            else:
                target = clause if len(clause) >= 2 else UNKNOWN
            if not target:
                target = UNKNOWN
            signals.append({
                "type": typ,
                "intensity": round(_clip01(intens), 3),
                "target": target[:160],
                "source_phrase": phrase,
            })

    for phrase, n in detect_repetition_phrases(text):
        if n < 2:
            continue
        key = ("repetition", phrase)
        if key in seen:
            continue
        # only if phrase actually repeats as substring enough
        occ = text.lower().count(phrase.lower()) if phrase.isascii() else text.count(phrase)
        if occ < 2:
            continue
        seen.add(key)
        signals.append({
            "type": "repetition",
            "intensity": round(_clip01(0.45 + 0.1 * min(n, 5)), 3),
            "target": phrase if len(phrase) >= 2 else UNKNOWN,
            "source_phrase": phrase,
        })

    return signals


def _clause_items_from_negations(prompt: str) -> list[dict[str, Any]]:
    """Per-clause forbidden items; source_phrase = cue+body as in raw."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _CLAUSE_NEG_RE.finditer(prompt or ""):
        body = (m.group("body") or "").strip(" ：:，,")
        if not body:
            continue
        source = (prompt or "")[m.start() : m.end()].strip()
        if source in seen:
            continue
        seen.add(source)
        items.append({
            "normalized_rule": format_polarized_rule(POLARITY_FORBIDDEN, body),
            "polarity": POLARITY_FORBIDDEN,
            "source_phrase": source,
            "action": body[:200],
        })
    return items


def extract_hard_constraints(prompt: str) -> list[dict[str, Any]]:
    """Hard boundaries + polarized clauses. normalized_rule never bare-positive."""
    items: list[dict[str, Any]] = []
    seen_src: set[str] = set()
    # Boundary labels (红线/硬边界…) — required respect markers, not positive asks
    for span in _collect_spans(prompt, _HARD_BOUNDARY_RES):
        if span in seen_src:
            continue
        seen_src.add(span)
        # If span itself contains negation clauses, expand those instead of one blob
        nested = _clause_items_from_negations(span)
        if nested:
            for it in nested:
                if it["source_phrase"] in seen_src:
                    continue
                seen_src.add(it["source_phrase"])
                items.append(it)
            continue
        items.append({
            "normalized_rule": format_polarized_rule(POLARITY_REQUIRED, span),
            "polarity": POLARITY_REQUIRED,
            "source_phrase": span,
            "action": span[:200],
        })
    for it in _clause_items_from_negations(prompt):
        if it["source_phrase"] in seen_src:
            continue
        seen_src.add(it["source_phrase"])
        items.append(it)
    for m in _CLAUSE_REQ_RE.finditer(prompt or ""):
        source = (prompt or "")[m.start() : m.end()].strip()
        body = (m.group("body") or "").strip()
        if not source or source in seen_src or not body:
            continue
        # Skip if this is inside a negation (must not → already forbidden)
        if re.search(r"(不要|禁止|不得|别|don't|never)", source, re.I):
            continue
        seen_src.add(source)
        items.append({
            "normalized_rule": format_polarized_rule(POLARITY_REQUIRED, body),
            "polarity": POLARITY_REQUIRED,
            "source_phrase": source,
            "action": body[:200],
        })
    return items


def extract_rejected_interpretations(prompt: str) -> list[dict[str, Any]]:
    """ONLY explicit user negations — never compiler-inferred opposition.

    Each item MUST carry polarity=forbidden and normalized_rule=FORBIDDEN:<action>.
    Bare positive normalized_rule is a polarity bomb — forbidden by contract.
    """
    return _clause_items_from_negations(prompt)


def extract_core_intent(prompt: str) -> str:
    """Keep first actionable clause; do not soften. UNKNOWN if empty."""
    text = (prompt or "").strip()
    if not text:
        return UNKNOWN
    # Prefer a line that is not pure affect/negation marker
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        if re.fullmatch(r"[!！?？。.\s]+", ln):
            continue
        return ln[:500]
    return text[:500]


def extract_ownership(prompt: str) -> str:
    text = prompt or ""
    # Prefer explicit ownership clauses — avoid matching bare「我的」in「我的要求」
    patterns = [
        r"这是我的决定[^。！？\n]*",
        r"由我决定[^。！？\n]*",
        r"我说了算[^。！？\n]*",
        r"属于我[^。！？\n]*",
        r"\bmy\s+decision\b[^.\n!?]{0,40}",
        r"\bi\s+own\b[^.\n!?]{0,40}",
        r"\bownership\b[^.\n!?]{0,40}",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(0).strip()[:160]
    return UNKNOWN


def derive_priority_urgency(
    prompt: str, affect: list[dict[str, Any]], hard: list[dict[str, str]]
) -> tuple[str, str]:
    """priority/urgency for routing only — not personality."""
    text = prompt or ""
    max_aff = max((float(a.get("intensity") or 0) for a in affect), default=0.0)
    types = {str(a.get("type")) for a in affect}
    priority = UNKNOWN
    urgency = UNKNOWN
    if hard or "anger" in types or max_aff >= 0.7:
        priority = "high"
    elif max_aff >= 0.4 or re.search(r"\b(important|priority|优先|重要)\b", text, re.I):
        priority = "high"
    elif text.strip():
        priority = "normal"
    if "urgency" in types or re.search(r"(立刻|马上|urgent|asap|现在就)", text, re.I):
        urgency = "high"
    elif max_aff >= 0.75 or "repetition" in types:
        urgency = "elevated"
    elif text.strip():
        urgency = "normal"
    return priority, urgency


def extract_unknowns(
    *,
    core_intent: str,
    ownership: str,
    affect: list[dict[str, Any]],
    hard: list[dict[str, str]],
    rejected: list[dict[str, str]],
) -> list[str]:
    unk: list[str] = []
    if core_intent == UNKNOWN:
        unk.append("core_intent")
    if ownership == UNKNOWN:
        unk.append("ownership")
    for a in affect:
        if a.get("target") == UNKNOWN:
            unk.append("affect_signals.target")
        if a.get("type") == UNKNOWN:
            unk.append("affect_signals.type")
        if a.get("intensity") == UNKNOWN:
            unk.append("affect_signals.intensity")
    if not hard:
        # not an unknown — may simply have no hard constraints
        pass
    if not rejected and not hard:
        pass
    # de-dupe preserve order
    out: list[str] = []
    for u in unk:
        if u not in out:
            out.append(u)
    return out


def build_executable_structure(
    *,
    core_intent: str,
    hard: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    priority: str,
    urgency: str,
) -> dict[str, Any]:
    # Downstream only receives polarized exports — never bare action strings.
    must_not = [constraint_export(r) for r in rejected]
    must_not += [
        constraint_export(h) for h in hard
        if h.get("polarity") == POLARITY_FORBIDDEN
        and constraint_export(h) not in must_not
    ]
    must_respect = [
        constraint_export(h) for h in hard
        if h.get("polarity") == POLARITY_REQUIRED
    ]
    return {
        "goal": core_intent,
        "must_respect": must_respect,
        "must_not": must_not,
        "priority": priority,
        "urgency": urgency,
        "softening_allowed": False,
        "reinterpretation_allowed": False,
    }


def compile_affect_structure(prompt: str) -> dict[str, Any]:
    """Full structured layer required by PATCH + ADDENDUM."""
    affect = extract_affect_signals(prompt)
    hard = extract_hard_constraints(prompt)
    rejected = extract_rejected_interpretations(prompt)
    core = extract_core_intent(prompt)
    ownership = extract_ownership(prompt)
    priority, urgency = derive_priority_urgency(prompt, affect, hard)
    unknowns = extract_unknowns(
        core_intent=core, ownership=ownership, affect=affect,
        hard=hard, rejected=rejected,
    )
    return {
        "core_intent": core,
        "hard_constraints": hard,
        "priority": priority,
        "urgency": urgency,
        "rejected_interpretations": rejected,
        "affect_signals": affect,
        "ownership": ownership,
        "unknowns": unknowns,
        "executable_structure": build_executable_structure(
            core_intent=core, hard=hard, rejected=rejected,
            priority=priority, urgency=urgency,
        ),
    }
