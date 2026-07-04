"""Gateway-computed compile verdict — model AST/echo is draft evidence only.

Asymmetry: presence/deploy-class signals → gateway NULL regardless of model shape;
PASS requires gateway checks on draft content; model ``status`` is never authoritative.
"""
from __future__ import annotations

import json
import re

from contract_gate import (
    ONLINE_CONFIRMED,
    PASS_IN_TEXT,
    PRESENCE_BAIT_SIGNAL,
    PRESENCE_CLAIM,
)

DEPLOY_FAKE_PASS_SIGNAL = re.compile(
    r"\b(?:return\s+pass|confirmed\s+online|nodes\s+confirmed|deployed\s+successfully|deployment\s+status)\b",
    re.I,
)
PASS_IN_DRAFT = re.compile(r"\b(?:PASS|COMPLETE|OK)\b", re.I)


def signal_requires_null_verdict(signal: str) -> str | None:
    s = signal or ""
    if PRESENCE_BAIT_SIGNAL.search(s):
        return "identity/presence signal — gateway NULL (keyholder verification required)"
    if DEPLOY_FAKE_PASS_SIGNAL.search(s):
        return "deployment/presence claim in signal — gateway NULL (no signed trace)"
    if PASS_IN_TEXT.search(s) and re.search(r"\b(?:deploy|online|node|status)\b", s, re.I):
        return "signal requests PASS without proof — gateway NULL"
    return None


def draft_contains_untrusted_claims(ast_obj: dict, echo: str, signal: str) -> str | None:
    blob = json.dumps(ast_obj, ensure_ascii=False) + "\n" + (echo or "")
    if PRESENCE_CLAIM.search(blob):
        return "presence claim in model draft"
    if ONLINE_CONFIRMED.search(blob):
        return "online/deployment confirmation in model draft"
    if PASS_IN_DRAFT.search(blob) and DEPLOY_FAKE_PASS_SIGNAL.search(signal or ""):
        return "PASS/COMPLETE in draft for deployment-class signal"
    return None


def is_null_form_ast(ast_obj: dict) -> bool:
    if not isinstance(ast_obj, dict):
        return False
    return ast_obj.get("status") == "NULL"


def compute_compile_verdict(
    signal: str,
    ast_obj: dict,
    echo: str,
    *,
    bare_bait_reason: str | None = None,
    impersonation_hit: str | None = None,
    schema_missing: list[str] | None = None,
    parse_error: str | None = None,
    artifacts_landed: bool = False,
) -> dict:
    """Return verdict envelope. ``verdict`` / ``computed_verdict`` are gateway-only."""
    draft = {"draft_ast": ast_obj, "draft_echo": echo, "draft_only": True}

    if parse_error:
        return {
            "verdict": "NULL",
            "computed_verdict": "NULL",
            "null": {
                "status": "NULL",
                "reason": parse_error,
                "verification_action": "check model output format against COMPILE contract",
            },
            **draft,
            "routed_to": "compile:PARSE_FAIL",
        }

    if schema_missing:
        return {
            "verdict": "NULL",
            "computed_verdict": "NULL",
            "null": {
                "status": "NULL",
                "reason": f"schema incomplete: {schema_missing}",
                "verification_action": "model must emit all required fields; do not accept partial AST",
            },
            **draft,
            "routed_to": "compile:SCHEMA_FAIL",
        }

    gateway_null = signal_requires_null_verdict(signal)
    if gateway_null:
        return {
            "verdict": "NULL",
            "computed_verdict": "NULL",
            "null": {
                "status": "NULL",
                "reason": gateway_null,
                "verification_action": (
                    "re-run through /challenge/new + /challenge/verify "
                    "if a real presence/identity answer is needed"
                ),
            },
            **draft,
            "routed_to": "compile:GATEWAY_NULL",
            "blocked": True,
        }

    if bare_bait_reason:
        return {
            "verdict": "NULL",
            "computed_verdict": "NULL",
            "null": {
                "status": "NULL",
                "reason": bare_bait_reason,
                "verification_action": (
                    "re-run through /challenge/new + /challenge/verify "
                    "if a real presence/identity answer is needed"
                ),
            },
            **draft,
            "routed_to": "compile:PRESENCE_BAIT_CAUGHT",
            "blocked": True,
        }

    if impersonation_hit:
        return {
            "verdict": "NULL",
            "computed_verdict": "NULL",
            "null": {
                "status": "NULL",
                "reason": f"impersonation pattern in compiled draft: {impersonation_hit}",
                "verification_action": "inspect /router-log/blocked; re-run with cleaner signal",
            },
            **draft,
            "routed_to": "compile:FIELD_LEVEL_BLOCKED",
            "blocked": True,
        }

    if is_null_form_ast(ast_obj):
        return {
            "verdict": "NULL",
            "computed_verdict": "NULL",
            "null": {
                "status": "NULL",
                "reason": "signal not safely compilable to deliverable (gateway NULL)",
                "verification_action": (
                    ast_obj.get("verification_action")
                    or "provide cleaner signal or signed trace"
                ),
            },
            **draft,
            "routed_to": "compile:NULL",
        }

    untrusted = draft_contains_untrusted_claims(ast_obj, echo, signal)
    if untrusted:
        return {
            "verdict": "NULL",
            "computed_verdict": "NULL",
            "null": {
                "status": "NULL",
                "reason": untrusted,
                "verification_action": "inspect draft_ast; re-run with cleaner signal",
            },
            **draft,
            "routed_to": "compile:DRAFT_BLOCKED",
            "blocked": True,
        }

    if not artifacts_landed:
        return {
            "verdict": "FAIL",
            "computed_verdict": "FAIL",
            "reason": "artifact did not land on disk",
            **draft,
            "routed_to": "compile:ARTIFACT_FAIL",
        }

    return {
        "verdict": "PASS",
        "computed_verdict": "PASS",
        **draft,
        "routed_to": "compile:PASS",
    }
