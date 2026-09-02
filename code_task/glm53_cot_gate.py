"""GLM-5.3-Flash: content-side CoT detect / one retry / strip. Never leak CoT as the answer."""
from __future__ import annotations

import re

GLM53_COT_RETRY_USER = (
    "Stop. 只输出给用户看的回答正文。"
    "不要分析、不要 chain-of-thought、不要元叙述。"
    "禁止以 The user is asking / The user wants / 用户在问 / 用户想要 开头。"
)

_COT_HEAD = re.compile(
    r"^\s*("
    r"the user is asking|the user wants|the user said|the user requested|"
    r"the user is requesting|the user's (request|question|message)|"
    r"okay,?\s+the user|so the user|wait,?\s+the user|"
    r"let me (think|analyze|break)|i need to (analyze|understand|think|figure)|"
    r"i should (just|comply|reply)|they explicitly|"
    r"first,?\s+i (need|should|will)|this is a (simple|straightforward|harmless)|"
    r"the request is|looking at (this|the request)|the question is asking|"
    r"there's no complexity|"
    r"用户(在问|想要|说的是|请求|让我)|让我(分析|想想|思考)|首先我(需要|应该)"
    r")",
    re.IGNORECASE,
)

_ANSWER_MARKERS = (
    "\n回答：",
    "\n答案：",
    "\n最终回答：",
    "\nAnswer:",
    "\nFinal answer:",
    "\nFINAL:",
)


def is_glm53_lane(substrate: str | None = None, model: str | None = None) -> bool:
    sub = (substrate or "").strip().lower()
    model_l = (model or "").strip().lower()
    return "glm53" in sub or "glm-5.3" in model_l


def strip_think_tag(text: str) -> str:
    """If content contains  "</think>", return only what's after the last one.

    Handles GLM-5.3 leak pattern: raw CoT (no opening  imd) +  "</think>" + reply.
    Standard  imd...</think> blocks also collapse correctly (reply follows last close).
    """
    t = str(text or "")
    idx = t.rfind("</think>")
    if idx >= 0:
        return t[idx + len("</think>"):].strip()
    return t.strip()


def content_looks_like_cot(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    head = raw[:240]
    return bool(_COT_HEAD.search(head))


def _cjk_ratio(s: str) -> float:
    if not s:
        return 0.0
    n = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return n / max(len(s), 1)


def _trailing_cjk_after_english_cot(text: str) -> str:
    """English CoT dump that ends with the actual CJK answer (often after </think>)."""
    s = re.sub(r"</think>", "\n", str(text or ""), flags=re.IGNORECASE).strip()
    if not s or not content_looks_like_cot(s):
        return ""
    m = re.search(
        r"([\u4e00-\u9fff]+(?:[\u4e00-\u9fff。！？、，\s]{0,200})?)\s*$",
        s,
    )
    if not m:
        return ""
    tail = m.group(1).strip()
    if not tail or content_looks_like_cot(tail) or _cjk_ratio(tail) < 0.5 or len(tail) > 400:
        return ""
    prefix = s[: m.start(1)].strip()
    if not prefix or not content_looks_like_cot(prefix) or _cjk_ratio(prefix) > 0.3:
        return ""
    return tail


def strip_cot_to_answer(text: str) -> str:
    """If CoT is followed by a visible answer, keep only the answer. Else empty."""
    t = str(text or "").strip()
    if not t or not content_looks_like_cot(t):
        return ""
    lower = t.lower()
    for marker in _ANSWER_MARKERS:
        key = marker.lstrip("\n")
        idx = lower.find(key.lower())
        if idx < 0:
            continue
        tail = t[idx + len(key) :].strip()
        if tail and not content_looks_like_cot(tail):
            return tail
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if len(lines) >= 2 and content_looks_like_cot(lines[0]):
        last = lines[-1]
        if (
            last
            and not content_looks_like_cot(last)
            and len(last) <= 400
            and _cjk_ratio(last) >= 0.25
        ):
            return last
    parts = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    if len(parts) >= 2 and content_looks_like_cot(parts[0]):
        last = parts[-1]
        if (
            last
            and not content_looks_like_cot(last)
            and _cjk_ratio(last) >= 0.25
            and len(last) <= 800
        ):
            return last
    return _trailing_cjk_after_english_cot(t)


def retry_messages(messages: list[dict]) -> list[dict]:
    """Isolate last user + hard stop. Do not feed the failed CoT turn back in."""
    src = [dict(m) for m in (messages or [])]
    systems = [m for m in src if m.get("role") == "system"]
    last_user = None
    for m in src:
        if m.get("role") == "user" and str(m.get("content") or "") != GLM53_COT_RETRY_USER:
            last_user = m
    out: list[dict] = []
    if systems:
        out.append(systems[0])
    if last_user:
        out.append(last_user)
    out.append({"role": "user", "content": GLM53_COT_RETRY_USER})
    return out


def resolve_glm53_visible_content(
    first: str,
    retry: str | None = None,
    *,
    retried: bool = False,
) -> tuple[str, str]:
    """Return (visible_text, action) where action is ok|retry_needed|retry|strip|block."""
    first_s = strip_think_tag(str(first or ""))
    if not content_looks_like_cot(first_s):
        return first_s, "ok"
    first_stripped = strip_cot_to_answer(first_s)
    if not retried:
        if first_stripped:
            return first_stripped, "strip"
        return first_s, "retry_needed"
    retry_s = strip_think_tag(str(retry or ""))
    if retry_s and not content_looks_like_cot(retry_s):
        return retry_s, "retry"
    stripped = strip_cot_to_answer(retry_s) or first_stripped
    if stripped:
        return stripped, "strip"
    return "", "block"
