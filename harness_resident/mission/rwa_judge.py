"""Runner-facing RWA card judgment. Calls judgment_for_card; never compares 及以上."""
from __future__ import annotations

from typing import Any

from harness.rwa_read import judgment_for_card, visible_judgment


def runner_judge_cards(cards: list[dict] | None) -> list[dict]:
    out = []
    for raw in cards or []:
        if not isinstance(raw, dict):
            continue
        card = dict(raw)
        card["judgment"] = visible_judgment(card)
        out.append(card)
    return out


def runner_results_from_cards(cards: list[dict] | None) -> dict[str, Any]:
    """Shape consumed by parse_judgment_payload → runner._parse_judgments."""
    results: dict[str, dict] = {}
    errors: list[str] = []
    for card in runner_judge_cards(cards):
        oid = str(card.get("symbol") or "").strip()
        if not oid:
            errors.append("missing_symbol")
            continue
        verdict = card["judgment"]
        if verdict == "HIT":
            mapped = "HIT"
            code = "in_scope"
        elif verdict == "MISS":
            mapped = "MISS"
            code = "out_of_scope"
        else:
            mapped = "UNDETERMINED"
            code = "insufficient_evidence"
        results[oid] = {
            "id": oid,
            "verdict": mapped,
            "reason_code": code,
            "reason": card.get("reject") or verdict,
            "evidence_ids": ["rwa.read"],
            "eligibility_assessment": "not_assessed",
            "missing_fields": [],
            "judgment": verdict,
        }
    return {
        "ok": not errors,
        "results": results,
        "missing": [],
        "extra": [],
        "duplicates": [],
        "errors": errors,
        "schema_version": 2,
        "source": "judgment_for_card",
    }


# Keep the enum function importable from the runner module path.
__all__ = [
    "judgment_for_card",
    "visible_judgment",
    "runner_judge_cards",
    "runner_results_from_cards",
]
