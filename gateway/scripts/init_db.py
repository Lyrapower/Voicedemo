"""Initialize sqlite DB: tokens + audit_log (with provider routing fields)."""
import sqlite3
import sys
from pathlib import Path

# Allow running as script from project root or from scripts/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DB_PATH


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS tokens (
            token_id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL,
            scopes TEXT NOT NULL,
            daily_limit INTEGER NOT NULL DEFAULT 100,
            daily_used INTEGER NOT NULL DEFAULT 0,
            daily_reset_at TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            token_id TEXT,
            endpoint TEXT NOT NULL,
            scope TEXT,
            status INTEGER NOT NULL,
            latency_ms INTEGER,
            req_bytes INTEGER,
            resp_bytes INTEGER,
            error TEXT,
            selected_provider TEXT,
            provider_fallback INTEGER,
            fallback_chain TEXT,
            mode TEXT,
            task_type TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
        CREATE INDEX IF NOT EXISTS idx_audit_token ON audit_log(token_id);
        """)
        conn.commit()
        print(f"DB initialized at {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
