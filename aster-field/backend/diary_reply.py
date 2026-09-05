from __future__ import annotations

import datetime as dt
import hashlib
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from typing import Iterable

from .diary_store import DB as DEFAULT_DB
from .diary_guard import reject_probe_text

MEMORY_DAYS = int(os.environ.get("ASTER_DIARY_MEMORY_DAYS", "7"))
LEASE_SECONDS = int(os.environ.get("ASTER_DIARY_LEASE_SECONDS", "300"))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: dt.datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def _parse_iso(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


@dataclass(frozen=True)
class LeasedReply:
    id: int
    entry_id: int
    text: str
    ts: str
    lease_token: str


class DiaryReplyStore:
    """Reply layer for the existing diary DB — separate append-only hash chain."""

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS replies(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    author TEXT NOT NULL CHECK(author IN ('lyra','aster')),
                    text TEXT NOT NULL CHECK(length(trim(text)) > 0),
                    ts TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending'
                        CHECK(state IN ('pending','leased','delivered')),
                    lease_token TEXT,
                    lease_expires_ts TEXT,
                    delivered_ts TEXT,
                    in_reply_to INTEGER,
                    prev_hash TEXT NOT NULL DEFAULT '',
                    hash TEXT NOT NULL,
                    FOREIGN KEY(entry_id) REFERENCES entries(id),
                    FOREIGN KEY(in_reply_to) REFERENCES replies(id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_replies_entry ON replies(entry_id,id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_replies_state ON replies(author,state,id)")
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def _entry(self, conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT id, ts, text FROM entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            raise KeyError(f"diary entry {entry_id} not found")
        return row

    def _append(
        self,
        entry_id: int,
        author: str,
        text: str,
        in_reply_to: int | None = None,
        *,
        _internal: bool = False,
    ) -> dict:
        clean = (text or "").strip()
        if not clean:
            raise ValueError("reply text required")
        reject_probe_text(clean, what="reply")
        if author not in {"lyra", "aster"}:
            raise ValueError("author must be lyra or aster")
        if author == "aster" and not _internal:
            raise PermissionError("refused: aster replies only via internal mailbox worker")

        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._entry(conn, entry_id)
            if in_reply_to is not None:
                parent = conn.execute(
                    "SELECT id, entry_id, author FROM replies WHERE id=?", (in_reply_to,)
                ).fetchone()
                if not parent or parent["entry_id"] != entry_id:
                    raise KeyError("in_reply_to does not belong to entry")
            previous = conn.execute("SELECT hash FROM replies ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = previous["hash"] if previous else ""
            ts = _iso()
            payload = "\x1f".join([prev_hash, str(entry_id), author, ts, clean, str(in_reply_to or "")])
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            state = "pending" if author == "lyra" else "delivered"
            delivered_ts = None if author == "lyra" else ts
            cur = conn.execute(
                """
                INSERT INTO replies(entry_id,author,text,ts,state,delivered_ts,in_reply_to,prev_hash,hash)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (entry_id, author, clean, ts, state, delivered_ts, in_reply_to, prev_hash, digest),
            )
            reply_id = int(cur.lastrowid)
            conn.commit()
        return {
            "id": reply_id,
            "entry_id": entry_id,
            "author": author,
            "text": clean,
            "ts": ts,
            "state": state,
            "hash": digest[:12],
            "in_reply_to": in_reply_to,
        }

    def add_lyra_reply(self, entry_id: int, text: str) -> dict:
        return self._append(entry_id, "lyra", text)

    def add_aster_response(
        self, entry_id: int, text: str, in_reply_to: int | None = None, *, _internal: bool = False
    ) -> dict:
        return self._append(entry_id, "aster", text, in_reply_to=in_reply_to, _internal=_internal)

    def thread(self, entry_id: int) -> dict:
        with self._conn() as conn:
            entry = self._entry(conn, entry_id)
            rows = conn.execute(
                """
                SELECT id,entry_id,author,text,ts,state,delivered_ts,in_reply_to,hash
                FROM replies WHERE entry_id=? ORDER BY id ASC
                """,
                (entry_id,),
            ).fetchall()
        return {
            "entry": dict(entry),
            "replies": [
                {
                    "id": row["id"],
                    "entry_id": row["entry_id"],
                    "author": row["author"],
                    "text": row["text"],
                    "ts": row["ts"],
                    "state": row["state"],
                    "delivered": row["state"] == "delivered",
                    "delivered_ts": row["delivered_ts"],
                    "in_reply_to": row["in_reply_to"],
                    "hash": row["hash"][:12],
                }
                for row in rows
            ],
        }

    def lease_pending(self, limit: int = 20, lease_seconds: int = LEASE_SECONDS) -> list[LeasedReply]:
        now = _now()
        expires = _iso(now + dt.timedelta(seconds=lease_seconds))
        token = uuid.uuid4().hex
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE replies SET state='pending', lease_token=NULL, lease_expires_ts=NULL
                WHERE author='lyra' AND state='leased' AND lease_expires_ts < ?
                """,
                (_iso(now),),
            )
            rows = conn.execute(
                """
                SELECT id,entry_id,text,ts FROM replies
                WHERE author='lyra' AND state='pending'
                ORDER BY id ASC LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE replies SET state='leased', lease_token=?, lease_expires_ts=? WHERE id IN ({placeholders})",
                    (token, expires, *ids),
                )
            conn.commit()
        return [LeasedReply(row["id"], row["entry_id"], row["text"], row["ts"], token) for row in rows]

    def ack_delivery(self, ids: Iterable[int], lease_token: str) -> int:
        clean_ids = [int(v) for v in ids]
        if not clean_ids or not lease_token:
            return 0
        now = _iso()
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in clean_ids)
            cur = conn.execute(
                f"""
                UPDATE replies
                SET state='delivered', delivered_ts=?, lease_token=NULL, lease_expires_ts=NULL
                WHERE author='lyra' AND state='leased' AND lease_token=? AND id IN ({placeholders})
                """,
                (now, lease_token, *clean_ids),
            )
            conn.commit()
            return cur.rowcount

    def release_lease(self, ids: Iterable[int], lease_token: str) -> int:
        clean_ids = [int(v) for v in ids]
        if not clean_ids or not lease_token:
            return 0
        with self._lock, self._conn() as conn:
            placeholders = ",".join("?" for _ in clean_ids)
            cur = conn.execute(
                f"""
                UPDATE replies SET state='pending',lease_token=NULL,lease_expires_ts=NULL
                WHERE author='lyra' AND state='leased' AND lease_token=? AND id IN ({placeholders})
                """,
                (lease_token, *clean_ids),
            )
            conn.commit()
            return cur.rowcount

    def memory_context(self, days: int = MEMORY_DAYS) -> dict:
        days = max(1, min(int(days), MEMORY_DAYS))
        cutoff = _now() - dt.timedelta(days=days)
        with self._conn() as conn:
            entries = conn.execute("SELECT id,ts,text FROM entries ORDER BY id DESC").fetchall()
            output = []
            for entry in entries:
                try:
                    entry_ts = _parse_iso(entry["ts"])
                except Exception:
                    continue
                replies = conn.execute(
                    "SELECT id,author,text,ts,state,in_reply_to FROM replies WHERE entry_id=? ORDER BY id",
                    (entry["id"],),
                ).fetchall()
                recent_replies = []
                for row in replies:
                    try:
                        if _parse_iso(row["ts"]) >= cutoff:
                            recent_replies.append(dict(row))
                    except Exception:
                        continue
                if entry_ts >= cutoff or recent_replies:
                    output.append({"entry": dict(entry), "replies": recent_replies})
        output.reverse()
        return {"days": days, "generated_at": _iso(), "threads": output}

    def verify(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id,entry_id,author,text,ts,in_reply_to,prev_hash,hash FROM replies ORDER BY id"
            ).fetchall()
        prev = ""
        for row in rows:
            payload = "\x1f".join(
                [prev, str(row["entry_id"]), row["author"], row["ts"], row["text"], str(row["in_reply_to"] or "")]
            )
            expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if row["prev_hash"] != prev or row["hash"] != expected:
                return {"ok": False, "broken_at_id": row["id"]}
            prev = row["hash"]
        return {"ok": True, "count": len(rows), "head": prev[:12] if prev else ""}
