"""Auto Fable distillation → 8501 /store/events (source=field_distill)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request
import datetime as dt
from pathlib import Path
from typing import Any

from field_lane.distill_record import DAILY_CAP, at_daily_cap, write_record
from field_lane.schema import (
    COMPILE_SEMANTICS_PARSE_ONLY,
    COMPILE_SEMANTICS_STRICT,
    SCHEMA_LOOSE,
    TEST_CONTENT_PREFIX,
)

logger = logging.getLogger("field_lane.distill")

_REPO = Path(__file__).resolve().parents[2]
_V5 = _REPO / "aster_grid_v5"
_TOKEN_PATH = _REPO / "grid-sovereign-runtime" / "config" / "grid_store.token"
_GRID_EVENTS = os.environ.get("GRID_EVENTS", "http://127.0.0.1:8501/store/events").rstrip("/")
_SOURCE = os.environ.get("FIELD_DISTILL_SOURCE", "field_distill")
_MIN_DRAFT_CHARS = int(os.environ.get("FIELD_DISTILL_MIN_CHARS", "40"))
# Auto-coach only on compile lanes; chat/diary archive without Fable spend.
DISTILL_TASKS = frozenset(
    t.strip()
    for t in os.environ.get("FIELD_DISTILL_TASKS", "compile_json,handoff_protocol").split(",")
    if t.strip()
)


def enabled() -> bool:
    return os.environ.get("FIELD_DISTILL_ENABLED", "1").lower() not in ("0", "false", "no")


def is_test_marked(*, test: bool | None = None, content: str | None = None) -> bool:
    if test is True:
        return True
    if content and str(content).startswith(TEST_CONTENT_PREFIX):
        return True
    return False


def should_distill(
    task: str,
    *,
    schema: str | None = None,
    compile_semantics: str | None = None,
    force: bool = False,
    allow_draft: bool = False,
    test: bool | None = None,
    content: str | None = None,
) -> bool:
    if is_test_marked(test=test, content=content):
        return False
    if force:
        if compile_semantics == COMPILE_SEMANTICS_PARSE_ONLY and not allow_draft:
            return False
        return True
    if compile_semantics == COMPILE_SEMANTICS_PARSE_ONLY:
        return False
    if schema == SCHEMA_LOOSE:
        return False
    if compile_semantics == COMPILE_SEMANTICS_STRICT:
        return task in DISTILL_TASKS
    # Legacy records without compile_semantics — original auto behavior.
    return task in DISTILL_TASKS


def _token() -> str:
    env = (os.environ.get("GRID_STORE_TOKEN") or "").strip()
    if env:
        return env
    if _TOKEN_PATH.is_file():
        return _TOKEN_PATH.read_text(encoding="utf-8").strip()
    return ""


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _http_json(url: str, payload: dict, *, timeout: float = 5.0) -> None:
    hdr = {"Content-Type": "application/json"}
    tok = _token()
    if tok:
        hdr["X-Grid-Token"] = tok
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=hdr,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout):
        pass


def emit_event(kind: str, **payload: Any) -> None:
    try:
        _http_json(_GRID_EVENTS, {"source": _SOURCE, "kind": kind, "payload": payload})
    except Exception as exc:
        logger.debug("field_distill emit %s failed: %s", kind, exc)


def distill_turn(
    instruction: str,
    draft: str,
    *,
    task: str,
    node_id: str,
    persona: str | None = None,
    client: str = "app",
    force: bool = False,
    schema: str | None = None,
    compile_semantics: str | None = None,
    allow_draft: bool = False,
    test: bool | None = None,
) -> dict[str, Any]:
    if not enabled():
        return {"skipped": True, "reason": "disabled"}

    if is_test_marked(test=test, content=draft):
        emit_event(
            "skip",
            task=task,
            node_id=node_id,
            client=client,
            persona=persona,
            reason="test_marked",
            compile_semantics=compile_semantics,
        )
        return {"skipped": True, "reason": "test_marked"}

    if force and compile_semantics == COMPILE_SEMANTICS_PARSE_ONLY and not allow_draft:
        emit_event(
            "reject",
            task=task,
            node_id=node_id,
            client=client,
            persona=persona,
            reason="parse_only_requires_allow_draft",
            compile_semantics=compile_semantics,
        )
        logger.info(
            "coach rejected parse_only without allow_draft task=%s client=%s",
            task,
            client,
        )
        return {"skipped": True, "reason": "parse_only_requires_allow_draft"}

    if not should_distill(
        task,
        schema=schema,
        compile_semantics=compile_semantics,
        force=force,
        allow_draft=allow_draft,
        test=test,
        content=draft,
    ):
        reason = "schema_loose" if schema == SCHEMA_LOOSE else "task_not_coach_eligible"
        if compile_semantics == COMPILE_SEMANTICS_PARSE_ONLY:
            reason = "parse_only_auto_blocked"
        emit_event(
            "skip",
            task=task,
            node_id=node_id,
            client=client,
            persona=persona,
            schema=schema,
            compile_semantics=compile_semantics,
            reason=reason,
        )
        return {"skipped": True, "reason": reason}

    instr = (instruction or "").strip()
    text = (draft or "").strip()
    if len(text) < _MIN_DRAFT_CHARS:
        emit_event(
            "skip",
            task=task,
            node_id=node_id,
            client=client,
            persona=persona,
            reason="draft_too_short",
            chars=len(text),
        )
        return {"skipped": True, "reason": "draft_too_short"}

    compile_ts = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")

    if at_daily_cap():
        row = write_record(
            node_id=node_id,
            compile_ts=compile_ts,
            instruction=instr,
            student_draft=text,
            task=task,
            client=client,
            persona=persona,
            coach=None,
            skip_reason="budget",
            compile_semantics=compile_semantics,
            test=test,
            allow_draft_override=allow_draft if compile_semantics == COMPILE_SEMANTICS_PARSE_ONLY else None,
        )
        emit_event(
            "distill_skipped_budget",
            task=task,
            node_id=node_id,
            client=client,
            persona=persona,
            record_id=row["record_id"],
            cap=DAILY_CAP,
        )
        return {"skipped": True, "reason": "budget", "record_id": row["record_id"]}

    trace = {
        "task": task,
        "node_id": node_id,
        "client": client,
        "persona": persona,
        "instruction_sha12": _sha12(instr),
        "draft_sha12": _sha12(text),
        "forced": force,
        "compile_semantics": compile_semantics,
        "allow_draft": allow_draft,
    }
    emit_event("queued", **trace)

    if str(_V5) not in sys.path:
        sys.path.insert(0, str(_V5))

    try:
        from distill.aster_distill_harness_v1_1 import collect_one  # noqa: WPS433

        result = collect_one(
            instr,
            draft=text,
            event_source=_SOURCE,
            node_id=node_id,
            task=task,
            client=client,
            persona=persona,
            compile_ts=compile_ts,
        )
        emit_event(
            "collect",
            **trace,
            run_id=result.get("id"),
            record_id=result.get("record_id"),
            coach_json_ok=result.get("coach_json_ok"),
            queued_for_review=result.get("queued_for_review"),
        )
        return {"ok": True, **result, **trace}
    except Exception as exc:
        name = type(exc).__name__
        emit_event("error", **trace, error=name, detail=str(exc)[:240])
        logger.warning("field_distill failed task=%s client=%s: %s", task, client, exc)
        return {"ok": False, "error": name, **trace}


# after_turn 必须落正文(截断),禁止只留 hash——2026-08-02: epoch 硬删后仅 sha 不可恢复
_ARCHIVE_TEXT_CAP = 12000


def archive_turn(
    instruction: str,
    draft: str,
    *,
    task: str,
    node_id: str,
    persona: str | None = None,
    client: str = "app",
    compile_semantics: str | None = None,
    test: bool | None = None,
) -> None:
    instr = (instruction or "").strip()
    body = (draft or "").strip()
    emit_event(
        "turn_archived",
        task=task,
        node_id=node_id,
        client=client,
        persona=persona,
        instruction_sha12=_sha12(instr),
        draft_sha12=_sha12(body),
        chars=len(body),
        instruction=instr[:_ARCHIVE_TEXT_CAP],
        draft=body[:_ARCHIVE_TEXT_CAP],
        text_capped=bool(len(instr) > _ARCHIVE_TEXT_CAP or len(body) > _ARCHIVE_TEXT_CAP),
        compile_semantics=compile_semantics,
        test=bool(test) if test is not None else is_test_marked(content=draft),
    )


def schedule_after_turn(
    instruction: str,
    draft: str,
    *,
    task: str,
    node_id: str,
    persona: str | None = None,
    client: str = "app",
    auto_coach: bool = True,
    schema: str | None = None,
    compile_semantics: str | None = None,
    test: bool | None = None,
) -> None:
    """Archive every turn; auto Fable coach only when auto_coach and compile task."""

    def _job() -> None:
        try:
            archive_turn(
                instruction,
                draft,
                task=task,
                node_id=node_id,
                persona=persona,
                client=client,
                compile_semantics=compile_semantics,
                test=test,
            )
            if auto_coach and should_distill(
                task,
                schema=schema,
                compile_semantics=compile_semantics,
                test=test,
                content=draft,
            ):
                distill_turn(
                    instruction,
                    draft,
                    task=task,
                    node_id=node_id,
                    persona=persona,
                    client=client,
                    schema=schema,
                    compile_semantics=compile_semantics,
                    test=test,
                )
        except Exception:
            logger.exception("schedule_after_turn failed")

    threading.Thread(target=_job, daemon=True, name="field-distill").start()


def schedule_coach(
    instruction: str,
    draft: str,
    *,
    task: str,
    node_id: str,
    persona: str | None = None,
    client: str = "app",
    compile_semantics: str | None = None,
    allow_draft: bool = False,
    test: bool | None = None,
) -> None:
    """Explicit Fable coach zone — manual / review; parse_only needs allow_draft."""

    def _job() -> None:
        try:
            distill_turn(
                instruction,
                draft,
                task=task,
                node_id=node_id,
                persona=persona,
                client=client,
                force=True,
                compile_semantics=compile_semantics,
                allow_draft=allow_draft,
                test=test,
            )
        except Exception:
            logger.exception("schedule_coach failed")

    threading.Thread(target=_job, daemon=True, name="field-coach").start()
