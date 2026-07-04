"""SQLite state store — config/state_persistence in config/aster.toml."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .aster_config import database_path, section


class LocalRouterStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or database_path()
        self._cache_size_mb = int(section("state_persistence").get("cache_size_mb", 10))

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute(f"PRAGMA cache_size = -{self._cache_size_mb * 1024}")
        return con

    def ensure_schema(self) -> None:
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS state (
                   session_id TEXT NOT NULL,
                   timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                   source TEXT DEFAULT 'lyra',
                   channel TEXT,
                   content TEXT,
                   embedding_content BLOB,
                   embedding_emotional BLOB,
                   PRIMARY KEY (session_id, timestamp)
                );
                CREATE INDEX IF NOT EXISTS idx_session ON state(session_id);
                CREATE INDEX IF NOT EXISTS idx_timestamp ON state(timestamp);
                CREATE INDEX IF NOT EXISTS idx_source ON state(source);
                CREATE INDEX IF NOT EXISTS idx_channel ON state(channel);
                """
            )
            con.commit()

    def insert_state(
        self,
        *,
        session_id: str,
        content: str,
        channel: str | None = None,
        source: str = "lyra",
        embedding_content: bytes | None = None,
        embedding_emotional: bytes | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO state (session_id, source, channel, content, embedding_content, embedding_emotional)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, source, channel, content, embedding_content, embedding_emotional),
            )
            con.commit()

    def recent(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT session_id, timestamp, source, channel, content
                FROM state WHERE session_id = ?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]


_store: LocalRouterStore | None = None


def get_local_router_store() -> LocalRouterStore:
    global _store
    if _store is None:
        _store = LocalRouterStore()
        _store.ensure_schema()
    return _store
