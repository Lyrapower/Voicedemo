"""Finish-reason normalization and chat transport audit metadata."""
from __future__ import annotations

import re
from typing import Any

UPSTREAM_CONTENT_FILTER = "content_filter"


def last_complete_sentence(text: str) -> str:
    t = (text or "").rstrip()
    if not t:
        return ""
    parts = re.split(r"(?<=[。！？!?\.])\s+", t)
    if len(parts) >= 2 and parts[-1] and not re.search(r"[。！？!?\.]$", parts[-1]):
        return " ".join(parts[:-1]).strip()
    return t


def normalize_finish_reason(
    upstream_finish: str,
    *,
    blocked: bool = False,
    block_source: str | None = None,
    block_rule: str | None = None,
    filter_source: str | None = None,
    filter_rule: str | None = None,
    exception_class: str | None = None,
) -> str:
    fr = str(upstream_finish or "unknown")
    if exception_class:
        if "Timeout" in exception_class:
            return "timeout"
        return "protocol_error"
    if blocked:
        if block_source == "impersonation":
            return "impersonation_block"
        if block_source == "contract_gate":
            return "contract_block"
        if block_source == "substrate_gate":
            return "substrate_rejection"
        if block_source == "sanitizer":
            return "sanitizer_rejection"
        return "protocol_error"
    if fr == UPSTREAM_CONTENT_FILTER:
        if filter_source and filter_rule:
            return UPSTREAM_CONTENT_FILTER
        return "protocol_error"
    if fr in ("length", "max_tokens"):
        return "length"
    if fr in ("stop", "end_turn"):
        return "stop"
    if fr == "unknown":
        return "stop"
    return fr


_INCOMPLETE_TAIL = re.compile(
    r"(?:[-:：]\s*|\*\*[^*\n]{0,120}$|\n\d+\.\s*$|\n-\s*[\*]?$)$",
)


def should_continue_chat(
    *,
    chat_route: str,
    upstream_finish: str,
    text: str,
    blocked: bool,
    prompt: str = "",
) -> bool:
    """Emergency-only — disabled by default; never keyword-shape answers."""
    import os
    if os.getenv("CHAT_CONTINUATION_EMERGENCY", "").strip() not in ("1", "true", "yes"):
        return False
    if chat_route != "chat" or blocked:
        return False
    if upstream_finish not in ("length", "max_tokens"):
        return False
    t = (text or "").rstrip()
    return len(t) >= 40 and t[-1] not in "。！？!?."


def build_finish_audit(
    *,
    upstream_finish: str,
    normalized_finish: str,
    blocked: bool = False,
    block_source: str | None = None,
    block_rule: str | None = None,
    filter_source: str | None = None,
    filter_rule: str | None = None,
    exception_class: str | None = None,
    raw_text: str = "",
    sanitized_text: str = "",
    selected_route: str = "chat",
    selected_contract: str = "none",
    token_counts: dict[str, Any] | None = None,
    stale_envelope_in_history: bool = False,
    continuation_retry: bool = False,
    continuation_attempt: int = 0,
    max_tokens_sent: int | None = None,
    budget_route: str | None = None,
) -> dict[str, Any]:
    return {
        "upstream_finish_reason": upstream_finish,
        "finish_reason": normalized_finish,
        "blocked": blocked,
        "block_source": block_source,
        "block_rule": block_rule,
        "filter_source": filter_source,
        "filter_rule": filter_rule,
        "exception_class": exception_class,
        "raw_text_len": len(raw_text or ""),
        "sanitized_text_len": len(sanitized_text or ""),
        "raw_text_preview": (raw_text or "")[:400],
        "sanitized_text_preview": (sanitized_text or "")[:400],
        "selected_route": selected_route,
        "selected_contract": selected_contract,
        "token_counts": token_counts or {},
        "stale_envelope_in_history": stale_envelope_in_history,
        "continuation_retry": continuation_retry,
        "continuation_attempt": continuation_attempt,
        "max_tokens_sent": max_tokens_sent,
        "budget_route": budget_route,
    }
