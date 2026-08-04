"""Affect / negation / hard-boundary provenance for intent compilation.

Deterministic only. No LLM. Does not soften, reframe, or invent goals.
UNKNOWN when unsure — never guess into rejected_interpretations.

INTENT_CONVERGE polarity (Commit D): executable_meaning is the sole execute
string. display_hint is log/human only — never enters canonical_core.
source_phrase is a literal raw slice; authoritative span = UTF-8 byte offsets.
Focus words in negation scope must survive into executable_meaning.
"""
from __future__ import annotations

import json
import re
from typing import Any

UNKNOWN = "UNKNOWN"

POLARITY_FORBIDDEN = "forbidden"
POLARITY_REQUIRED = "required"
POLARITY_UNCERTAIN = "uncertain"
POLARITY_RELEASED = "released"
POLARITY_QUOTED = "quoted"  # cited text — not a Lyra constraint

# Negation lexicon (longest-first match). 别的 ≠ 别.
NEGATION_LEXICON: tuple[str, ...] = (
    "绝不能", "不可以", "不要", "不准", "不许", "别再", "禁止", "拒绝", "停止",
    "不得", "不再", "杜绝", "勿", "别",
    "must not", "do not", "don't", "cannot", "can't", "no more", "never", "stop",
)

# Focus words — must enter executable_meaning, not only source_phrase.
FOCUS_WORDS: tuple[str, ...] = ("只", "仅", "都", "全", "一定", "总是", "光", "净")


def utf8_byte_span(raw: str, char_start: int, char_end: int) -> tuple[int, int]:
    """Char indices → UTF-8 byte offsets (authoritative provenance)."""
    if char_start < 0 or char_end < char_start or char_end > len(raw or ""):
        raise ValueError("invalid char span for utf8_byte_span")
    start_b = len((raw or "")[:char_start].encode("utf-8"))
    end_b = start_b + len((raw or "")[char_start:char_end].encode("utf-8"))
    return start_b, end_b


def phrase_from_utf8_span(raw: str, start_b: int, end_b: int) -> str:
    return (raw or "").encode("utf-8")[start_b:end_b].decode("utf-8")


def _strip_leading_negation_cue(text: str) -> str:
    s = (text or "").strip()
    for cue in NEGATION_LEXICON:
        if s.startswith(cue):
            return s[len(cue):].strip(" ：:，,")
    return s


def _focus_preserving_action(source_phrase: str, action: str) -> str:
    """If focus words sit in the negation body, keep them in executable rule text."""
    body = _strip_leading_negation_cue(source_phrase)
    out = (action or "").strip()
    for fw in sorted(FOCUS_WORDS, key=len, reverse=True):
        if fw in body and fw not in out:
            return body[:200] if body else UNKNOWN
    if not out:
        return body[:200] if body else UNKNOWN
    return out[:200]

# Required / request cues (not negation).
_REQ_CUES = (
    "不但要", "还要", "我要你", "要你", "必须", "务必", "只能", "先修", "先",
    "照.+做", "也要",
)

_AFFECT_CUES: list[tuple[str, re.Pattern[str], float]] = [
    ("anger", re.compile(r"(愤怒|生气|火大|受够了|烦死|气死|怒|愤怒地|怒了)", re.I), 0.85),
    ("anger", re.compile(r"\b(angry|furious|pissed|outrage|mad\s+at)\b", re.I), 0.8),
    ("frustration", re.compile(r"(烦透|折腾|又来|第\s*\d+\s*次|再三|反复说了)", re.I), 0.7),
    ("frustration", re.compile(
        r"\b(frustrat\w*|sick\s+of|enough\s+already|again\s+and\s+again)\b", re.I), 0.7),
    ("urgency", re.compile(r"(立刻|马上|赶紧|刻不容缓|现在就|紧急)", re.I), 0.75),
    ("urgency", re.compile(r"\b(urgent|immediately|right\s+now|asap|critical)\b", re.I), 0.75),
    ("emphasis", re.compile(r"(重点是|听清楚|我说的是|必须听懂|强调)", re.I), 0.65),
    ("emphasis", re.compile(r"\b(listen|i\s+said|pay\s+attention|emphasiz\w*)\b", re.I), 0.6),
]


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _span_target(span: str) -> str:
    """Object fragment for affect windows only — NOT for constraint rules."""
    s = span.strip()
    for cue in NEGATION_LEXICON:
        if s.startswith(cue):
            s = s[len(cue):].strip(" ：:，,")
            break
    return s[:120] if len(s) >= 2 else UNKNOWN


# ---------------------------------------------------------------------------
# Quote masking (L)
# ---------------------------------------------------------------------------

# System self-ingestion markers — pasted receipts are inert unless endorsed.
_SELF_INGEST_LINE = re.compile(
    r"(?m)^[ \t]*(?:FORBIDDEN|REQUIRED|UNCERTAIN)\s*:.*$"
)
_SELF_INGEST_BLOCK = re.compile(
    r"(?s)(?:"
    r"```.*?```|"
    r"\{[^{}]*\"(?:polarity|normalized_rule|display_hint|source_phrase|executable_meaning)\"[^{}]*\}|"
    r"_diag/[^\s]+|"
    r"compiler receipt.*?(?:\n\n|\Z)|"
    r"structured(?:_compile)?(?:_sample)?(?:\.json)?[^\n]*"
    r")"
)


def find_quoted_ranges(text: str) -> list[tuple[int, int]]:
    """Ranges that are citations / code / system receipts — inert by default."""
    ranges: list[tuple[int, int]] = []
    t = text or ""
    for cre in (
        re.compile(r"```.*?```", re.S),
        re.compile(r"「[^」]*」"),
        re.compile(r"“[^”]*”"),
        re.compile(r"\"[^\"]*\""),
        re.compile(r"以下是[^：:]*[：:][^\n]*"),
        re.compile(r"他说[^。！？\n]*"),
        re.compile(r"她说[^。！？\n]*"),
        _SELF_INGEST_LINE,
        _SELF_INGEST_BLOCK,
    ):
        for m in cre.finditer(t):
            ranges.append((m.start(), m.end()))
    # contiguous FORBIDDEN:/REQUIRED: dump blocks (no DOTALL — do not eat outer speech)
    for m in re.finditer(
        r"(?m)(?:^[ \t]*(?:FORBIDDEN|REQUIRED|UNCERTAIN)\s*:.*\n?)+",
        t,
    ):
        ranges.append((m.start(), m.end()))
    ranges.sort()
    return _merge_ranges(ranges)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    out = [ranges[0]]
    for a, b in ranges[1:]:
        pa, pb = out[-1]
        if a <= pb:
            out[-1] = (pa, max(pb, b))
        else:
            out.append((a, b))
    return out


def _adoption_ranges(raw: str) -> list[tuple[int, int, str]]:
    """「采用其中 X」→ promote only X from otherwise quoted paste."""
    out: list[tuple[int, int, str]] = []
    for m in re.finditer(r"采用其中\s*([^\n。！？]+)", raw or ""):
        frag = (m.group(1) or "").strip()
        if frag:
            out.append((m.start(1), m.end(1), frag))
    return out


def _outer_negates_paste(raw: str) -> bool:
    """User explicitly rejects pasted system content (f14c)."""
    return bool(re.search(
        r"(不要采用|别采用|忽略(?:其中|以上|这段|粘贴)|不采纳|作废|当没看见)",
        raw or "",
    ))


def _in_ranges(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in ranges)


def _span_in_quoted(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    if start >= end:
        return False
    # majority of span inside quote → quoted
    mid = (start + end) // 2
    return _in_ranges(mid, ranges)


# ---------------------------------------------------------------------------
# Polarity authority — executable_meaning sole execute string; display_hint log-only
# ---------------------------------------------------------------------------

# Whitelist for constraint slices inside canonical_core (construct, never strip-copy).
CANONICAL_CORE_CONSTRAINT_KEYS = frozenset({
    "executable_meaning",
    "polarity",
    "source_phrase",
    "source_start_byte",
    "source_end_byte",
})

_BANNED_CORE_KEYS = frozenset({
    "display_hint", "normalized_rule", "action", "releases",
    "source_start", "source_end", "uncertain_scope",
})

_HUMAN_PREFIX_RE = re.compile(r"^(FORBIDDEN|REQUIRED|UNCERTAIN)\s*:")


def assert_constraint_well_formed(item: dict[str, Any]) -> None:
    """Hard fail if polarity missing, prefix-smuggled, or provenance incomplete."""
    if not isinstance(item, dict):
        raise ValueError("constraint must be a dict with polarity")
    pol = item.get("polarity")
    if pol not in (
        POLARITY_FORBIDDEN, POLARITY_REQUIRED, POLARITY_UNCERTAIN,
        POLARITY_RELEASED, POLARITY_QUOTED,
    ):
        raise ValueError("constraint missing/invalid polarity (sole authority)")
    if "normalized_rule" in item:
        raise ValueError("normalized_rule retired; use display_hint (log) + executable_meaning")
    meaning = str(item.get("executable_meaning") or "")
    hint = str(item.get("display_hint") or "")
    if pol != POLARITY_QUOTED:
        if _HUMAN_PREFIX_RE.match(meaning) or _HUMAN_PREFIX_RE.match(hint):
            raise ValueError("polarity prefix forbidden in executable_meaning/display_hint")
    if not meaning and pol in (POLARITY_FORBIDDEN, POLARITY_REQUIRED):
        raise ValueError("executable_meaning required for executable polarities")
    if pol in (POLARITY_FORBIDDEN, POLARITY_REQUIRED):
        src = str(item.get("source_phrase") or "")
        body = _strip_leading_negation_cue(src)
        for fw in FOCUS_WORDS:
            if fw in body and fw not in meaning:
                raise ValueError(
                    "focus word %r in source scope missing from executable_meaning" % fw
                )
    if "source_start_byte" not in item or "source_end_byte" not in item:
        raise ValueError("constraint missing UTF-8 byte provenance")


def constraint_log_label(item: dict[str, Any]) -> str:
    """Human/log display only — never use as execute authority."""
    assert_constraint_well_formed(item)
    pol = item["polarity"]
    hint = str(item.get("display_hint") or item.get("source_phrase") or "")
    return "%s:%s" % (str(pol).upper(), hint)


def assert_canonical_core_safe(obj: Any, *, _path: str = "$") -> None:
    """Exit guard: canonical_core must not carry display fields or human prefixes."""
    if isinstance(obj, dict):
        if "display_hint" in obj or "normalized_rule" in obj:
            raise ValueError(
                "canonical_core forbids display_hint/normalized_rule at %s (hard fail)" % _path
            )
        for k in obj:
            if k in _BANNED_CORE_KEYS:
                raise ValueError(
                    "canonical_core forbids key %r at %s (hard fail)" % (k, _path)
                )
        # constraint-shaped objects: exact whitelist only
        if "polarity" in obj or "executable_meaning" in obj:
            extra = set(obj.keys()) - CANONICAL_CORE_CONSTRAINT_KEYS
            if extra:
                raise ValueError(
                    "canonical_core non-whitelist keys %s at %s (hard fail)"
                    % (sorted(extra), _path)
                )
        for k, v in obj.items():
            assert_canonical_core_safe(v, _path="%s.%s" % (_path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_canonical_core_safe(v, _path="%s[%d]" % (_path, i))
    elif isinstance(obj, str):
        if _HUMAN_PREFIX_RE.match(obj):
            raise ValueError(
                "canonical_core forbids human polarity prefix at %s (hard fail)" % _path
            )


def build_canonical_core_constraint(item: dict[str, Any]) -> dict[str, Any]:
    """Whitelist-construct execute constraint — never copy-then-delete."""
    assert_constraint_well_formed(item)
    if item["polarity"] not in (POLARITY_FORBIDDEN, POLARITY_REQUIRED):
        raise ValueError("canonical_core constraint only for forbidden/required")
    meaning = str(item["executable_meaning"])
    if not meaning:
        raise ValueError("executable_meaning empty")
    core = {
        "executable_meaning": meaning,
        "polarity": item["polarity"],
        "source_phrase": item["source_phrase"],
        "source_start_byte": int(item["source_start_byte"]),
        "source_end_byte": int(item["source_end_byte"]),
    }
    # enforce exact key set
    if set(core.keys()) != CANONICAL_CORE_CONSTRAINT_KEYS:
        raise ValueError("canonical_core key set mismatch")
    assert_canonical_core_safe(core)
    return core


def serialize_canonical_core_constraints(items: list[dict[str, Any]]) -> str:
    """Stable one-line JSON array of whitelist constraint cores."""
    cores = [
        build_canonical_core_constraint(i)
        for i in items
        if i.get("polarity") in (POLARITY_FORBIDDEN, POLARITY_REQUIRED)
    ]
    cores.sort(key=lambda c: (c["source_start_byte"], c["source_end_byte"]))
    blob = json.dumps(cores, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert_canonical_core_safe(json.loads(blob))
    if "display_hint" in blob or "normalized_rule" in blob:
        raise ValueError("canonical_core serialization leaked display fields")
    if "FORBIDDEN:" in blob or "REQUIRED:" in blob or "UNCERTAIN:" in blob:
        raise ValueError("canonical_core serialization leaked human polarity prefix")
    return blob


def constraint_export_for_execute(item: dict[str, Any]) -> dict[str, Any]:
    """Execute-bound export = canonical_core constraint slice (no display_hint)."""
    assert_constraint_well_formed(item)
    if item["polarity"] == POLARITY_UNCERTAIN:
        raise ValueError("uncertain constraint cannot enter execute")
    if item["polarity"] == POLARITY_QUOTED:
        raise ValueError("quoted citation cannot enter execute")
    if item["polarity"] == POLARITY_RELEASED:
        raise ValueError("released constraint excluded from execute set")
    return build_canonical_core_constraint(item)


def fake_downstream_read_display_hint(canonical_core: dict[str, Any]) -> str:
    """Fake consumer that only trusts display_hint — must hard-fail on canonical_core."""
    assert_canonical_core_safe(canonical_core)
    if "display_hint" in canonical_core:
        raise ValueError("display_hint leaked into canonical_core")
    raise ValueError(
        "hard fail: display_hint not available in canonical_core (not an execute field)"
    )


def bare_executable_meaning_alone_is_fail(payload: Any) -> bool:
    """Naked executable_meaning (no polarity + span) must not be consumable."""
    if isinstance(payload, str):
        return True
    if isinstance(payload, dict):
        if "executable_meaning" in payload and "polarity" not in payload:
            return True
        if "display_hint" in payload and "polarity" not in payload:
            return True
        if "normalized_rule" in payload:
            return True
        try:
            constraint_export_for_execute(payload)
            return False
        except (ValueError, KeyError, TypeError):
            return True
    return True


# back-compat name used by older tests
def bare_normalized_rule_alone_is_fail(payload: Any) -> bool:
    return bare_executable_meaning_alone_is_fail(payload)


# ---------------------------------------------------------------------------
# Clause split + negation scope
# ---------------------------------------------------------------------------

def _is_negation_cue_at(text: str, i: int) -> str | None:
    """Return lexicon cue at offset i, or None. Reject 别的 for 别."""
    rest = text[i:]
    for cue in NEGATION_LEXICON:
        if not rest.lower().startswith(cue.lower() if cue.isascii() else cue):
            continue
        if cue == "别":
            # 别的 / 别人 / 别处 — not imperative 别
            nxt = rest[len(cue):len(cue) + 1]
            if nxt in ("的", "人", "处", "名", "样"):
                continue
        return cue
    return None


def _split_top_clauses(text: str) -> list[tuple[int, int, str]]:
    """Split on ，、；;。.!！？?:：\n — return (start, end, clause).

    Fullwidth ！ / ： matter: without them, '说了三遍！不要…' stays one clause and
    cue-prefix rejects 不要 → silent uncertain (fail-open risk).
    """
    out: list[tuple[int, int, str]] = []
    start = 0
    for i, ch in enumerate(text or ""):
        if ch in "，、；;\n。.!！？?：:":
            chunk = text[start:i].strip()
            if chunk:
                # trim offsets to chunk
                rs = text.find(chunk, start, i)
                re_ = rs + len(chunk)
                out.append((rs, re_, chunk))
            start = i + 1
    if start < len(text or ""):
        chunk = text[start:].strip()
        if chunk:
            rs = text.find(chunk, start)
            out.append((rs, rs + len(chunk), chunk))
    return out


def _mk_item(
    *,
    raw: str,
    start: int,
    end: int,
    polarity: str,
    action: str,
    releases: dict | None = None,
) -> dict[str, Any]:
    source = raw[start:end]
    meaning = _focus_preserving_action(source, action)
    start_b, end_b = utf8_byte_span(raw, start, end)
    if phrase_from_utf8_span(raw, start_b, end_b) != source:
        raise ValueError("UTF-8 byte span does not round-trip to source_phrase")
    # display_hint = raw slice (human); executable_meaning = scoped action (execute)
    item = {
        "display_hint": source,
        "executable_meaning": meaning,
        "polarity": polarity,
        "source_phrase": source,
        "source_start_byte": start_b,
        "source_end_byte": end_b,
        # char offsets: internal only (non-authoritative; not in canonical_core)
        "source_start": start,
        "source_end": end,
        "action": meaning,
    }
    if releases:
        item["releases"] = releases
    assert_constraint_well_formed(item)
    assert source == raw[start:end]
    assert source in raw  # literal substring — never rewrite
    return item


def _action_after_cue(clause: str, cue: str) -> str:
    body = clause[len(cue):].strip(" ：:，,") if clause.startswith(cue) else clause
    return body[:200] if body else UNKNOWN


# 和 inside these bigrams is NOT a conjunctive splitter (温和建议 ≠ 温 + 建议).
_AND_COMPOUND_BIGRAMS = frozenset({
    "温和", "平和", "总和", "缓和", "饱和", "几何", "和尚", "和气",
    "和谐", "和约", "和解", "和平", "暖和", "中和", "柔和", "调和",
    "附和", "应和", "共和", "维和", "说和",
})


def _is_conjunctive_he(raw: str, i: int) -> bool:
    """True if raw[i] is a real conjunctive 和/与/、 not a compound glyph."""
    if i < 0 or i >= len(raw):
        return False
    ch = raw[i]
    if ch == "、":
        return True
    if ch not in ("和", "与"):
        return False
    if i > 0 and raw[i - 1:i + 1] in _AND_COMPOUND_BIGRAMS:
        return False
    return True


def _distribute_he_conjuncts(
    raw: str, cue_start: int, cue: str, body_start: int, body_end: int,
) -> list[dict[str, Any]]:
    """禁止A和B → two forbidden; source_phrase = literal slices only (C/f6)."""
    def _single() -> list[dict[str, Any]]:
        return [_mk_item(
            raw=raw, start=cue_start, end=body_end, polarity=POLARITY_FORBIDDEN,
            action=_action_after_cue(raw[cue_start:body_end], cue),
        )]

    parts: list[tuple[int, int]] = []
    buf_s = body_start
    i = body_start
    while i < body_end:
        if _is_conjunctive_he(raw, i) and i > buf_s:
            parts.append((buf_s, i))
            buf_s = i + 1
        i += 1
    if buf_s < body_end:
        parts.append((buf_s, body_end))
    if len(parts) <= 1:
        return _single()
    if any((b - a) < 2 for a, b in parts):
        return _single()
    items = []
    for pi, (a, b) in enumerate(parts):
        if pi == 0:
            items.append(_mk_item(
                raw=raw, start=cue_start, end=b, polarity=POLARITY_FORBIDDEN,
                action=raw[a:b].strip()[:200] or UNKNOWN,
            ))
        else:
            items.append(_mk_item(
                raw=raw, start=a, end=b, polarity=POLARITY_FORBIDDEN,
                action=raw[a:b].strip()[:200] or UNKNOWN,
            ))
    return items


def _parse_required_clause(raw: str, start: int, end: int, clause: str) -> dict[str, Any] | None:
    # 不但要X / 还要Y / 我要你Z / 也要W / 先修Q / 必须…
    patterns = [
        (re.compile(r"^(不但要)(.+)$"), 1),
        (re.compile(r"^(还要)(.+)$"), 1),
        (re.compile(r"^(也要)(.+)$"), 1),
        (re.compile(r"^(我要你)(.+)$"), 1),
        (re.compile(r"^(要你)(.+)$"), 1),
        (re.compile(r"^(必须|务必|只能)(.+)$"), 1),
        (re.compile(r"^(先修)(.+)$"), 1),
        (re.compile(r"^(先)(.+)$"), 1),
        (re.compile(r"^(照.+做)[：:]?\s*(.*)$"), 1),  # endorsement shell
    ]
    for cre, _ in patterns:
        m = cre.match(clause)
        if not m:
            continue
        # 先 + 修极性 ok; 先 alone weak — still required if body
        action = (m.group(m.lastindex) or "").strip()  # type: ignore[arg-type]
        if not action and m.lastindex and m.lastindex >= 1:
            action = clause
        if cre.pattern.startswith("^(照"):
            # handled elsewhere (f12)
            continue
        if not action:
            continue
        return _mk_item(
            raw=raw, start=start, end=end, polarity=POLARITY_REQUIRED, action=action,
        )
    return None


def _looks_like_negation_tone(text: str) -> bool:
    return bool(re.search(
        r"(不要|不准|不许|禁止|不得|勿|拒绝|别(?!的)|不再|停止|难道|岂能)",
        text or "",
    ))



def _has_endorsement_before(raw: str, pos: int) -> bool:
    window = raw[max(0, pos - 40):pos]
    return bool(re.search(r"照\s*\S+?\s*说的做[：:]\s*$", window))


def _classify_uncertain_scope(clause: str) -> str:
    """whole = block entire execute; local = drop only this item (fail-closed default whole)."""
    c = clause or ""
    if re.search(r"(目标|授权|红线|硬|验收|决定|交付|边界|核心)", c):
        return "whole"
    if re.search(r"(禁止|不要|不得|软化|总结|解释|极性)", c):
        return "whole"
    if re.search(r"(或许|可能|好像|未必)", c):
        return "local"
    return "whole"


def extract_constraint_items(prompt: str) -> list[dict[str, Any]]:
    raw = prompt or ""
    quoted = find_quoted_ranges(raw)
    items: list[dict[str, Any]] = []
    consumed: list[tuple[int, int]] = []
    reject_paste = _outer_negates_paste(raw)

    def mark(a: int, b: int) -> None:
        consumed.append((a, b))

    def overlaps_consumed(a: int, b: int) -> bool:
        return any(not (b <= x or a >= y) for x, y in consumed)

    # Pass -1: self-ingest / quote spans → quoted (inert). Adoption handled later.
    for a, b in quoted:
        if overlaps_consumed(a, b):
            continue
        frag = raw[a:b]
        if not frag.strip():
            continue
        # strip leading log-prefix from action so quoted payload is inert text only
        action = frag.strip()[:200]
        action = re.sub(
            r"^(?:FORBIDDEN|REQUIRED|UNCERTAIN)\s*:\s*", "", action, flags=re.M,
        ).strip() or frag.strip()[:200]
        items.append(_mk_item(
            raw=raw, start=a, end=b, polarity=POLARITY_QUOTED,
            action=action,
        ))
        mark(a, b)

    # Pass -0.5: explicit adoption 「采用其中 X」→ parse X as live constraint
    if not reject_paste:
        for m in re.finditer(r"采用其中\s*([^\n。！？]+)", raw):
            frag = (m.group(1) or "").strip()
            a, b = m.start(1), m.end(1)
            mark(m.start(), m.end())  # consume whole adoption directive
            if not frag:
                continue
            for it in extract_constraint_items(frag):
                if it["polarity"] in (POLARITY_FORBIDDEN, POLARITY_REQUIRED):
                    items.append(_mk_item(
                        raw=raw, start=a, end=b,
                        polarity=it["polarity"],
                        action=it["executable_meaning"],
                    ))

    # Pass 0: endorsement 照…说的做：body
    for m in re.finditer(
        r"照\s*\S+?\s*说的做[：:]\s*", raw,
    ):
        if overlaps_consumed(m.start(), m.end()):
            continue
        body_start = m.end()
        # body until sentence end
        body_end = len(raw)
        for sep in ("。", "！", "？", "\n"):
            j = raw.find(sep, body_start)
            if j != -1:
                body_end = min(body_end, j)
        body = raw[body_start:body_end]
        # parse body as if Lyra (ignore quote masks inside endorsement body)
        for start, end, clause in _split_top_clauses(body):
            abs_s, abs_e = body_start + start, body_start + end
            if overlaps_consumed(abs_s, abs_e):
                continue
            found_cue = None
            found_off = None
            for i in range(abs_s, abs_e):
                c = _is_negation_cue_at(raw, i)
                if c:
                    found_cue, found_off = c, i
                    break
            if found_cue and found_off is not None:
                items.append(_mk_item(
                    raw=raw, start=found_off, end=abs_e,
                    polarity=POLARITY_FORBIDDEN,
                    action=raw[found_off + len(found_cue):abs_e].strip() or UNKNOWN,
                ))
                mark(found_off, abs_e)
        mark(m.start(), body_end)

    # Pass 1: clauses (forbids/requires first — releases need prior forbids)
    for start, end, clause in _split_top_clauses(raw):
        if overlaps_consumed(start, end):
            continue

        if _span_in_quoted(start, end, quoted):
            # already marked in pass -1; skip
            continue

        # f10 corrective opener
        if clause.startswith("不是不要"):
            mark(start, end)
            continue

        # f14c: meta about paste — not a domain constraint
        if re.match(r"^(不要采用|别采用|忽略(?:其中|以上|这段|粘贴)|不采纳)", clause):
            mark(start, end)
            continue

        # find negation cue (may follow affect preface / 红线：)
        found_cue = None
        found_off = None
        for i in range(start, end):
            c = _is_negation_cue_at(raw, i)
            if not c:
                continue
            prefix = raw[start:i]
            ps = prefix.strip()
            ok_prefix = (
                ps in ("", "也", "又", "且", "并", "我是")
                or prefix.endswith("我是")
                or prefix.endswith(("：", ":"))
                or ("：" in prefix or ":" in prefix)
                or bool(re.search(r"(愤怒|生气|火大|受够)", prefix))
                or ps.startswith("红线")
            )
            if not ok_prefix:
                continue
            found_cue, found_off = c, i
            break

        if found_cue and found_off is not None:
            body_start = found_off + len(found_cue)
            while body_start < end and raw[body_start] in " \t：:":
                body_start += 1
            src_start = found_off
            if raw[start:found_off].strip() in ("也", "我是"):
                src_start = start
            body = raw[body_start:end]
            if re.search(r"[和与、]", body) and not re.search(
                r"(不要|禁止|不得|别|不准|不许)", body,
            ):
                for it in _distribute_he_conjuncts(
                    raw, src_start, found_cue, body_start, end,
                ):
                    items.append(it)
                    mark(int(it["source_start"]), int(it["source_end"]))
            else:
                items.append(_mk_item(
                    raw=raw, start=src_start, end=end,
                    polarity=POLARITY_FORBIDDEN,
                    action=raw[body_start:end].strip() or UNKNOWN,
                ))
                mark(src_start, end)
            continue

        req = _parse_required_clause(raw, start, end, clause)
        if req:
            # f8: 别的不说 skipped — 先修极性
            if clause.startswith("别的"):
                continue
            items.append(req)
            mark(start, end)
            continue

        if clause.startswith("别的"):
            continue

        if _looks_like_negation_tone(clause):
            # fail-closed: negation tone without lexicon scope → uncertain (never default required)
            unc = _mk_item(
                raw=raw, start=start, end=end, polarity=POLARITY_UNCERTAIN,
                action=clause[:200],
            )
            unc["uncertain_scope"] = _classify_uncertain_scope(clause)
            items.append(unc)
            mark(start, end)

    # Boundary labels
    for m in re.finditer(r"红线[：:][^\n。！？]+", raw):
        if overlaps_consumed(m.start(), m.end()) or _span_in_quoted(m.start(), m.end(), quoted):
            continue
        # prefer nested forbids already extracted
        if any(_is_negation_cue_at(raw, i) for i in range(m.start(), m.end())):
            continue
        items.append(_mk_item(
            raw=raw, start=m.start(), end=m.end(), polarity=POLARITY_REQUIRED,
            action=raw[m.start():m.end()].strip()[:200],
        ))

    # Pass 2: releases (M) — after forbids exist; flip matching forbidden → released
    for m in re.finditer(r"现在可以([^。！？\n]+?)了", raw):
        if overlaps_consumed(m.start(), m.end()):
            continue
        act = (m.group(1) or "").strip()
        if not act:
            continue
        target = None
        for prev in items:
            if prev.get("polarity") == POLARITY_FORBIDDEN and (
                act in str(prev.get("executable_meaning") or "")
                or str(prev.get("executable_meaning") or "") in act
            ):
                target = {
                    "executable_meaning": prev["executable_meaning"],
                    "source_start_byte": prev["source_start_byte"],
                    "source_end_byte": prev["source_end_byte"],
                }
                prev["polarity"] = POLARITY_RELEASED
                prev["releases"] = {"by_source": raw[m.start():m.end()]}
                break
        items.append(_mk_item(
            raw=raw, start=m.start(), end=m.end(), polarity=POLARITY_RELEASED,
            action=act, releases=target or {"executable_meaning": act},
        ))
        mark(m.start(), m.end())

    return items


def extract_rejected_interpretations(prompt: str) -> list[dict[str, Any]]:
    """Forbidden (and only forbidden) — explicit user negations."""
    return [
        it for it in extract_constraint_items(prompt)
        if it.get("polarity") == POLARITY_FORBIDDEN
    ]


def extract_hard_constraints(prompt: str) -> list[dict[str, Any]]:
    """All constraint items except pure quoted (quoted stays out of hard list)."""
    return [
        it for it in extract_constraint_items(prompt)
        if it.get("polarity") != POLARITY_QUOTED
    ]


# ---------------------------------------------------------------------------
# Affect / ownership / core (unchanged spirit)
# ---------------------------------------------------------------------------

def detect_repetition_phrases(prompt: str) -> list[tuple[str, int]]:
    text = prompt or ""
    counts: dict[str, int] = {}
    cjk = re.findall(r"[\u4e00-\u9fff]+", text)
    for run in cjk:
        for n in (3, 4, 5, 6, 7, 8):
            if len(run) < n:
                continue
            for i in range(0, len(run) - n + 1):
                gram = run[i : i + n]
                counts[gram] = counts.get(gram, 0) + 1
    for t in re.findall(r"[A-Za-z]{3,24}", text):
        counts[t.lower()] = counts.get(t.lower(), 0) + 1
    for ln in (ln.strip() for ln in text.splitlines() if ln.strip()):
        counts[ln] = counts.get(ln, 0) + 1
    out: list[tuple[str, int]] = []
    for k, n in counts.items():
        occ = text.lower().count(k.lower()) if k.isascii() else text.count(k)
        if occ >= 2 and 2 <= len(k) <= 40:
            out.append((k, occ))
    out.sort(key=lambda x: (-len(x[0]), -x[1]))
    kept: list[tuple[str, int]] = []
    for phrase, n in out:
        if any(phrase != p and phrase in p and n <= m for p, m in kept):
            continue
        kept.append((phrase, n))
        if len(kept) >= 8:
            break
    return kept


def extract_affect_signals(prompt: str) -> list[dict[str, Any]]:
    text = prompt or ""
    signals: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    bangs = len(re.findall(r"[!！]{2,}", text))
    letters = [c for c in text if c.isalpha()]
    caps_ratio = (
        sum(1 for c in letters if c.isupper()) / len(letters) if letters else 0.0
    )
    for typ, cre, base in _AFFECT_CUES:
        for m in cre.finditer(text):
            phrase = m.group(0).strip()
            key = (typ, phrase)
            if key in seen:
                continue
            seen.add(key)
            intens = base + (min(0.15, 0.05 * bangs) if bangs else 0)
            if caps_ratio >= 0.55 and len(letters) >= 8:
                intens += 0.1
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
            after = re.split(r"[：:]", clause, maxsplit=1)
            target = after[1].strip() if len(after) == 2 and after[1].strip() else clause
            signals.append({
                "type": typ,
                "intensity": round(_clip01(intens), 3),
                "target": (target or UNKNOWN)[:160],
                "source_phrase": phrase,
            })
    for phrase, n in detect_repetition_phrases(text):
        if n < 2:
            continue
        key = ("repetition", phrase)
        if key in seen:
            continue
        occ = text.lower().count(phrase.lower()) if phrase.isascii() else text.count(phrase)
        if occ < 2:
            continue
        seen.add(key)
        signals.append({
            "type": "repetition",
            "intensity": round(_clip01(0.45 + 0.1 * min(n, 5)), 3),
            "target": phrase,
            "source_phrase": phrase,
        })
    return signals


def extract_core_intent(prompt: str) -> str:
    text = (prompt or "").strip()
    if not text:
        return UNKNOWN
    for ln in (ln.strip() for ln in text.splitlines() if ln.strip()):
        if not re.fullmatch(r"[!！?？。.\s]+", ln):
            return ln[:500]
    return text[:500]


def extract_ownership(prompt: str) -> str:
    text = prompt or ""
    for pat in (
        r"这是我的决定[^。！？\n]*",
        r"由我决定[^。！？\n]*",
        r"我说了算[^。！？\n]*",
        r"属于我[^。！？\n]*",
        r"\bmy\s+decision\b[^.\n!?]{0,40}",
        r"\bi\s+own\b[^.\n!?]{0,40}",
    ):
        m = re.search(pat, text, re.I)
        if m:
            return m.group(0).strip()[:160]
    return UNKNOWN


def derive_priority_urgency(
    prompt: str, affect: list[dict[str, Any]], hard: list[dict[str, Any]],
) -> tuple[str, str]:
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
    hard: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> list[str]:
    del hard, rejected
    unk: list[str] = []
    if core_intent == UNKNOWN:
        unk.append("core_intent")
    if ownership == UNKNOWN:
        unk.append("ownership")
    for a in affect:
        if a.get("target") == UNKNOWN:
            unk.append("affect_signals.target")
    out: list[str] = []
    for u in unk:
        if u not in out:
            out.append(u)
    return out


def disambiguation_question(uncertain_items: list[dict[str, Any]]) -> str:
    """H · uncertain must bubble a human-answerable question."""
    phrases = [str(u.get("source_phrase") or "") for u in uncertain_items]
    joined = " / ".join(p for p in phrases if p) or "（未解析片段）"
    return "这句是要求还是禁令？→ %s" % joined


def build_executable_structure(
    *,
    core_intent: str,
    hard: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    priority: str,
    urgency: str,
) -> dict[str, Any]:
    """Execute: required/forbidden only. whole-uncertain blocks all; local drops item."""
    all_items = list(hard)
    seen = {
        (i.get("source_start_byte"), i.get("source_end_byte"), i.get("polarity"))
        for i in all_items
    }
    for r in rejected:
        key = (r.get("source_start_byte"), r.get("source_end_byte"), r.get("polarity"))
        if key not in seen:
            all_items.append(r)
            seen.add(key)

    uncertain = [i for i in all_items if i.get("polarity") == POLARITY_UNCERTAIN]
    whole_unc = [
        u for u in uncertain
        if u.get("uncertain_scope", "whole") != "local"
    ]
    blocked = bool(whole_unc)
    must_not: list[dict[str, Any]] = []
    must_respect: list[dict[str, Any]] = []
    if not blocked:
        for i in all_items:
            pol = i.get("polarity")
            if pol == POLARITY_FORBIDDEN:
                must_not.append(constraint_export_for_execute(i))
            elif pol == POLARITY_REQUIRED:
                must_respect.append(constraint_export_for_execute(i))
            # local uncertain / released / quoted skipped

    ask = whole_unc if blocked else uncertain
    return {
        "goal": core_intent,
        "must_respect": must_respect,
        "must_not": must_not,
        "priority": priority,
        "urgency": urgency,
        "softening_allowed": False,
        "reinterpretation_allowed": False,
        "execute_blocked": blocked,
        "disambiguation_question": (
            disambiguation_question(ask) if ask else None
        ),
    }


def compile_affect_structure(prompt: str) -> dict[str, Any]:
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
    # surface uncertain into unknowns list as well
    if any(h.get("polarity") == POLARITY_UNCERTAIN for h in hard):
        if "constraint.uncertain" not in unknowns:
            unknowns.append("constraint.uncertain")
    return {
        "core_intent": core,
        "hard_constraints": hard,
        "priority": priority,
        "urgency": urgency,
        "rejected_interpretations": rejected,
        "affect_signals": affect,
        "ownership": ownership,
        "unknowns": unknowns,
        "negation_lexicon": list(NEGATION_LEXICON),
        "executable_structure": build_executable_structure(
            core_intent=core, hard=hard, rejected=rejected,
            priority=priority, urgency=urgency,
        ),
    }


def format_polarized_rule(polarity: str, action: str) -> str:
    """Log-only label. Not for execute authority."""
    pol = polarity if polarity in (
        POLARITY_FORBIDDEN, POLARITY_REQUIRED, POLARITY_UNCERTAIN,
        POLARITY_RELEASED, POLARITY_QUOTED,
    ) else POLARITY_UNCERTAIN
    return "%s:%s" % (pol.upper(), action or "")


def constraint_export(item: dict[str, Any]) -> dict[str, Any]:
    return constraint_export_for_execute(item)


def bare_rule_readable_as_positive(text: str) -> bool:
    """Bare strings without polarity are never safe to execute."""
    r = (text or "").strip()
    if not r or r == UNKNOWN:
        return False
    return True
