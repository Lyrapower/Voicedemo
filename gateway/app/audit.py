"""Audit every request to sqlite (including 401/403/429/503)."""
import sqlite3
import time
from typing import Any, Optional

from app.config import DB_PATH


def log(
    token_id: Optional[str],
    endpoint: str,
    scope: Optional[str],
    status: int,
    latency_ms: Optional[int] = None,
    req_bytes: Optional[int] = None,
    resp_bytes: Optional[int] = None,
    error: Optional[str] = None,
    selected_provider: Optional[str] = None,
    provider_fallback: Optional[bool] = None,
    fallback_chain: Optional[str] = None,
    mode: Optional[str] = None,
    task_type: Optional[str] = None,
) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO audit_log (
                ts, token_id, endpoint, scope, status, latency_ms,
                req_bytes, resp_bytes, error,
                selected_provider, provider_fallback, fallback_chain, mode, task_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts,
                token_id,
                endpoint,
                scope,
                status,
                latency_ms,
                req_bytes,
                resp_bytes,
                error,
                selected_provider,
                1 if provider_fallback else 0 if provider_fallback is False else None,
                fallback_chain,
                mode,
                task_type,
            ),
        )
        conn.commit()
    finally:
        conn.close()
