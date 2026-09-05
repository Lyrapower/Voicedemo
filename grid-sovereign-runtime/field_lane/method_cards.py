"""Session seed + method card retrieval for compile/chat turns."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from field_lane.lane import current_epoch_start, node_for_task

_REPO = Path(__file__).resolve().parents[2]
_CARDS_PATH = Path(os.environ.get("METHOD_CARDS_PATH", str(_REPO / "traces" / "distill" / "method_cards.jsonl")))


def session_seed(*, node_id: str, task: str) -> str:
    start = current_epoch_start()
    payload = f"{node_id}|{task}|{start.isoformat()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[a-zA-Z_]{3,}", text or "")}


def _score_card(card: dict[str, Any], *, task: str, instruction: str) -> int:
    if str(card.get("status") or "active") != "active":
        return -1
    if card.get("allowed_for_prompt_retrieval") is False:
        return -1
    score = 0
    if str(card.get("task_kind") or "") == task:
        score += 3
    q = _tokenize(instruction)
    blob = " ".join(
        str(card.get(k) or "")
        for k in ("trigger", "better_move", "boundary", "verifier_rule", "move")
    )
    tags = card.get("tags") or []
    if isinstance(tags, list):
        blob += " " + " ".join(str(t) for t in tags)
    for tok in _tokenize(blob):
        if tok in q:
            score += 1
    return score


def load_cards() -> list[dict[str, Any]]:
    if not _CARDS_PATH.is_file():
        return []
    out: list[dict[str, Any]] = []
    with _CARDS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def cards_from_approved_records(*, limit: int = 20) -> list[dict[str, Any]]:
    from field_lane.distill_record import load_records
    from field_lane.review_state import resolve_status

    out: list[dict[str, Any]] = []
    for rec in load_records():
        rid = str(rec.get("record_id") or "")
        if not rid or resolve_status(rid) != "approved":
            continue
        coach = rec.get("coach")
        if not isinstance(coach, dict):
            continue
        mc = coach.get("method_card")
        if not isinstance(mc, dict):
            continue
        out.append(
            {
                "id": f"rec_{rid[:8]}",
                "task_kind": rec.get("task") or "compile_json",
                "status": "active",
                "allowed_for_prompt_retrieval": True,
                "trigger": mc.get("trigger"),
                "better_move": mc.get("move") or coach.get("better_move"),
                "boundary": coach.get("missing_boundary"),
                "verifier_rule": mc.get("verifier_rule"),
                "tags": [str(coach.get("failure_type") or "")],
            }
        )
        if len(out) >= limit:
            break
    return out


def retrieve_cards(*, task: str, instruction: str, limit: int = 3) -> list[dict[str, Any]]:
    pool = load_cards() + cards_from_approved_records()
    ranked: list[tuple[int, dict[str, Any]]] = []
    for card in pool:
        s = _score_card(card, task=task, instruction=instruction)
        if s > 0:
            ranked.append((s, card))
    ranked.sort(key=lambda x: (-x[0], str(x[1].get("id") or "")))
    return [c for _, c in ranked[: max(1, limit)]]


def format_lessons_block(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return ""
    lines = ["LOCAL OPERATING LESSONS (method cards — not raw Fable):"]
    for i, c in enumerate(cards, 1):
        lines.append(f"{i}. trigger: {c.get('trigger') or '—'}")
        lines.append(f"   better_move: {c.get('better_move') or c.get('move') or '—'}")
        lines.append(f"   boundary: {c.get('boundary') or '—'}")
        lines.append(f"   verifier_rule: {c.get('verifier_rule') or '—'}")
    return "\n".join(lines)


def inject_messages(
    messages: list[dict[str, Any]],
    *,
    task: str,
    instruction: str,
    node_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    nid = node_id or node_for_task(task)
    seed = session_seed(node_id=nid, task=task)
    cards = retrieve_cards(task=task, instruction=instruction)
    block = format_lessons_block(cards)
    meta = {
        "session_seed": seed,
        "method_cards_used": [str(c.get("id") or "") for c in cards],
        "method_card_count": len(cards),
    }
    if not block:
        return messages, meta
    sys_msg = {"role": "system", "content": block + f"\n\nsession_seed:{seed}"}
    return [sys_msg, *messages], meta
