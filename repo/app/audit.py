"""Grid audit log — AST hash + token count only (no user text)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

LOG_DIR = Path(__file__).resolve().parents[1] / "logs" / "grid_audit"
LOG_FILE = LOG_DIR / "grid.log.jsonl"


def log_transmission(
    *,
    audit_id: str,
    ast_hash: Union[int, str],
    token_count: int,
    backend: str,
    coherence_score: float,
) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "audit_id": audit_id,
        "ast_hash": ast_hash,
        "token_count": int(token_count),
        "backend": backend,
        "coherence_score": round(float(coherence_score), 4),
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
