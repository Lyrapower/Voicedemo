"""Small helpers for grid_store.db reads — always close connections."""
from __future__ import annotations

import sqlite3
from pathlib import Path

_BASE = Path(__file__).resolve().parent


def store_db_path() -> Path:
    return _BASE.parent / "grid-sovereign-runtime" / "data" / "grid_store.db"


def store_query_one(sql: str, params: tuple = ()) -> tuple | None:
    db = store_db_path()
    if not db.is_file():
        return None
    with sqlite3.connect(str(db)) as conn:
        return conn.execute(sql, params).fetchone()


def store_query_all(sql: str, params: tuple = ()) -> list[tuple]:
    db = store_db_path()
    if not db.is_file():
        return []
    with sqlite3.connect(str(db)) as conn:
        return conn.execute(sql, params).fetchall()
