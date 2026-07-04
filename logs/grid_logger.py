from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


LOG_PATH = Path("logs/grid_audit/grid.log.jsonl")


def _ensure_log_dir() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log_grid_event(ast_hash: int | str, token_count: int) -> None:
    _ensure_log_dir()
    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ast_hash": ast_hash,
        "token_count": int(token_count),
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

