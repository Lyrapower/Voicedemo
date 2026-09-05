"""L0 review runner — code_source tracking, GLM lane stats, rejection evidence."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import db

CODE_SOURCE_GLM = "glm_generated"
CODE_SOURCE_SUBSTITUTE = "substitute"
CODE_SOURCE_MANUAL = "manual"
CODE_SOURCE_FIX = "glm_fix_error"

LANE_GLM = "glm"
LANE_PIPELINE_SMOKE = "pipeline_smoke"

L0_REJECTION_DIR = Path(
    os.getenv(
        "L0_REJECTION_DIR",
        str(Path(os.getenv("PLATFORM_DB", "/data/platform.db")).parent / "store" / "l0_rejections"),
    )
)


def ensure_l0_schema(c) -> None:
    cols = {r[1] for r in c.execute("PRAGMA table_info(factor_reviews)").fetchall()}
    if "code_source" not in cols:
        c.execute("ALTER TABLE factor_reviews ADD COLUMN code_source TEXT")
    if "lane" not in cols:
        c.execute("ALTER TABLE factor_reviews ADD COLUMN lane TEXT")
    if "quarantine" not in cols:
        c.execute("ALTER TABLE factor_reviews ADD COLUMN quarantine INTEGER DEFAULT 0")
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS glm_lane_stats(
          id INTEGER PRIMARY KEY,
          review_id INTEGER NOT NULL UNIQUE,
          draft_id INTEGER NOT NULL,
          created INTEGER NOT NULL,
          outcome TEXT NOT NULL,
          code_source TEXT NOT NULL,
          lane TEXT NOT NULL,
          meta TEXT);
        CREATE INDEX IF NOT EXISTS ix_glm_lane_stats_source ON glm_lane_stats(code_source);
        """
    )


def _parse_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def glm_code_original(meta_raw: str | None) -> str:
    meta = _parse_meta(meta_raw)
    return (meta.get("glm_code_original") or "").strip()


def attach_glm_original(meta_raw: str | None, code: str) -> str:
    meta = _parse_meta(meta_raw)
    meta.setdefault("glm_code_original", (code or "").strip())
    meta.setdefault("code_source_at_propose", CODE_SOURCE_GLM)
    return json.dumps(meta, ensure_ascii=False)


def resolve_code_source(
    *,
    code: str,
    meta_raw: str | None,
    review_kind: str = "review",
) -> str:
    """Classify reviewed code: glm_generated | glm_fix_error | substitute | manual."""
    original = glm_code_original(meta_raw)
    current = (code or "").strip()
    if review_kind == "substitute":
        return CODE_SOURCE_SUBSTITUTE
    if not original:
        return CODE_SOURCE_MANUAL
    if current == original:
        return CODE_SOURCE_GLM
    if _normalize_code(current) == _normalize_code(original):
        return CODE_SOURCE_GLM
    # Grid fix_error path keeps glm lineage if still structurally GLM-derived
    if meta_raw and _parse_meta(meta_raw).get("last_fix_error"):
        return CODE_SOURCE_FIX
    return CODE_SOURCE_SUBSTITUTE


def _normalize_code(code: str) -> str:
    return re.sub(r"\s+", " ", (code or "").strip())


def assert_glm_lane_eligible(code_source: str) -> None:
    if code_source != CODE_SOURCE_GLM:
        raise ValueError(
            f"GLM lane stats blocked for code_source={code_source!r} "
            f"(only {CODE_SOURCE_GLM!r} allowed)"
        )


def record_glm_lane_stat(
    c,
    *,
    review_id: int,
    draft_id: int,
    outcome: str,
    code_source: str,
    lane: str,
    meta: dict[str, Any] | None = None,
) -> None:
    """Hard gate: non-glm_generated never enters glm_lane_stats."""
    assert_glm_lane_eligible(code_source)
    if lane != LANE_GLM:
        raise ValueError(f"GLM lane stats blocked for lane={lane!r}")
    c.execute(
        "INSERT OR IGNORE INTO glm_lane_stats(review_id, draft_id, created, outcome, code_source, lane, meta) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            review_id,
            draft_id,
            int(time.time()),
            outcome,
            code_source,
            lane,
            json.dumps(meta or {}, ensure_ascii=False),
        ),
    )


def write_rejection_record(
    *,
    draft_id: int,
    review_id: int | None,
    glm_code: str,
    rejection_error: str,
    rejection_detail: dict[str, Any] | None = None,
    trigger_lines: list[int] | None = None,
    note: str = "",
) -> Path:
    L0_REJECTION_DIR.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d", time.gmtime())
    path = L0_REJECTION_DIR / f"{day}.jsonl"
    record = {
        "ts": int(time.time()),
        "draft_id": draft_id,
        "review_id": review_id,
        "status": "glm_code_rejected",
        "quarantine": True,
        "glm_code_original": glm_code,
        "rejection_error": rejection_error,
        "rejection_detail": rejection_detail or {},
        "trigger_lines": trigger_lines or _import_trigger_lines(glm_code),
        "note": note,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def _import_trigger_lines(code: str) -> list[int]:
    lines: list[int] = []
    for i, line in enumerate((code or "").splitlines(), start=1):
        s = line.strip()
        if s.startswith("import ") or s.startswith("from "):
            lines.append(i)
    return lines


def capture_sandbox_rejection(code: str, db_path: str, watchlist: list[str]) -> dict[str, Any]:
    """Run sandbox to capture rejection payload for evidence jsonl."""
    import factor_sandbox

    detail: dict[str, Any] = {}
    try:
        factor_sandbox._validate_ast(code)
        detail["ast_scan"] = "pass"
    except factor_sandbox.SandboxError as exc:
        detail["ast_scan"] = {"category": exc.category, "error": str(exc), "type": type(exc).__name__}
    try:
        factor_sandbox.run_factor_review(code, db_path, watchlist)
        detail["runtime"] = "pass"
    except factor_sandbox.SandboxError as exc:
        detail["runtime"] = {"category": exc.category, "error": str(exc), "type": type(exc).__name__}
    except Exception as exc:
        detail["runtime"] = {"category": "pipeline", "error": str(exc), "type": type(exc).__name__}
    return detail
