"""Distill smoke vocabulary isolation + coach §2 status vocab gate."""
from __future__ import annotations

import json
import re
from typing import Any

# Production / review-gate reserved — smoke & toy tasks must not use as field names.
RESERVED_PRODUCTION_FIELD_NAMES = frozenset(
    {
        "record_id",
        "compile_ts",
        "review_status",
        "status",
        "node_id",
        "review",
        "decided_by",
        "decided_at",
        "review_version",
        "run_id",
        "fable_response_hash",
        "skip_reason",
        "coach",
        "coach_raw",
        "cli_meta",
        "gated_ok",
        "gated_reason",
        "violations",
    }
)

# Isolated smoke/toy handoff field names (do not collide with production ledger).
SMOKE_SAFE_FIELD_NAMES = ("artifact_ref", "compile_marker", "gate_phase")

# DISTILL REVIEW GATE spec §2 — sole legal review-decision enum values.
LEGAL_REVIEW_STATUSES = frozenset({"pending", "approved", "rejected", "held"})

COACH_STATUS_VOCAB_BLOCK = (
    "§2 REVIEW GATE STATUS VOCAB (if you name a human review decision state, ONLY these four):\n"
    "  pending | approved | rejected | held\n"
    "Never invent status enums (e.g. pending_review, accepted, passed, fail).\n"
    "Smoke/toy compile tasks: use fictive field names only "
    f"({', '.join(SMOKE_SAFE_FIELD_NAMES)}). "
    "Do NOT use production reserved names in minimal_correction examples: "
    "record_id, node_id, review_status, status, compile_ts, review, decided_by, …"
)

_STATUS_KEY_RE = re.compile(r"(^|_)(status|verdict|state)(_|$)|review_status|gate_phase", re.I)
_ENUM_LIKE_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")


def smoke_handoff_instruction() -> str:
    return (
        "compile_json smoke: three-field toy handoff for vocab-isolated acceptance. "
        "Use field names artifact_ref, compile_marker, gate_phase only."
    )


def smoke_handoff_draft(*, purpose: str = "acceptance step 1") -> str:
    return json.dumps(
        {
            "toy": "smoke_packet",
            "schema_version": 1,
            "field_names": list(SMOKE_SAFE_FIELD_NAMES),
            "purpose": purpose,
        },
        ensure_ascii=False,
    )


def smoke_draft_violations(draft: str) -> list[str]:
    """Return reserved production field names found as JSON keys in a smoke draft."""
    try:
        obj = json.loads(draft)
    except json.JSONDecodeError:
        return []
    found: list[str] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k) in RESERVED_PRODUCTION_FIELD_NAMES:
                    found.append(str(k))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return sorted(set(found))


def _is_status_key(key: str) -> bool:
    return bool(_STATUS_KEY_RE.search(str(key)))


def _legal_status_value(value: str) -> bool:
    return value.strip().lower() in LEGAL_REVIEW_STATUSES


def _check_status_value(path: str, value: str, violations: list[str]) -> None:
    v = value.strip()
    if not v or not _ENUM_LIKE_RE.match(v):
        return
    if _legal_status_value(v):
        return
    violations.append(f"{path}={v}")


def scan_coach_vocab(coach: dict[str, Any] | None, coach_raw: str | None = None) -> list[str]:
    """Find status-like enum values outside §2 legal vocab in coach output."""
    violations: list[str] = []
    if not isinstance(coach, dict):
        return violations

    def walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{path}.{k}" if path else str(k)
                if isinstance(v, str) and _is_status_key(str(k)):
                    _check_status_value(p, v, violations)
                walk(v, p)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    walk(coach)

    mc = coach.get("minimal_correction")
    if isinstance(mc, str) and mc.strip().startswith("{"):
        try:
            walk(json.loads(mc), "minimal_correction")
        except json.JSONDecodeError:
            pass

    # Quoted enum-like tokens adjacent to status vocabulary in raw JSON text.
    if coach_raw:
        for m in re.finditer(
            r'"(?:review_status|status|verdict|gate_phase)"\s*:\s*"([a-z][a-z0-9_]*)"',
            coach_raw,
            flags=re.I,
        ):
            _check_status_value(f"coach_raw:{m.group(0)[:40]}", m.group(1), violations)

    return sorted(set(violations))


def apply_vocab_gate(
    record_id: str,
    coach: dict[str, Any] | None,
    coach_raw: str | None = None,
    *,
    decisions_path=None,
    records_path=None,
) -> list[str] | None:
    """Auto-hold record when coach output uses §2-outside status enums."""
    violations = scan_coach_vocab(coach, coach_raw)
    if not violations:
        return None
    from field_lane.review_state import append_decision

    detail = "; ".join(violations[:8])
    append_decision(
        record_id,
        "held",
        reason=f"violation:invalid_vocab — {detail}",
        decided_by="system",
        via="vocab_gate",
        decisions_path=decisions_path,
        records_path=records_path,
    )
    return violations
