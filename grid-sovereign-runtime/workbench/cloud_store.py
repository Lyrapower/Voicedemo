"""8515 Cloud 旁路记忆 — 与 8501 grid_store / workbench-b11 完全独立."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

ACTIVE_TURN_LIMIT = 15
ACTIVE_MSG_LIMIT = ACTIVE_TURN_LIMIT * 2

_LANE_ALIASES = {
    "glm52": "cloud-glm52",
    "kimi_k25": "cloud-kimi",
    "deepseek_v4": "cloud-ds",
    "smoke": "cloud-smoke",
    "cloud-glm52": "cloud-glm52",
    "cloud-kimi": "cloud-kimi",
    "cloud-ds": "cloud-ds",
    "cloud-smoke": "cloud-smoke",
}

PRODUCTION_CLOUD_LANES = frozenset({"cloud-glm52", "cloud-kimi", "cloud-ds"})
SMOKE_CLOUD_LANE = "cloud-smoke"

_AGENT_TEST_USER = re.compile(r"^u\d+$", re.I)
_AGENT_TEST_ASST = re.compile(r"^a\d+$", re.I)


class CloudAgentWriteForbidden(PermissionError):
    """Agent / smoke write blocked on production Cloud memory lane."""


def assert_cloud_agent_write_allowed(lane: str, user: str, assistant: str) -> None:
    key = CloudStore.normalize_lane(lane)
    if key == SMOKE_CLOUD_LANE or key not in PRODUCTION_CLOUD_LANES:
        return
    u = str(user or "").strip()
    a = str(assistant or "").strip()
    if _AGENT_TEST_USER.fullmatch(u) and _AGENT_TEST_ASST.fullmatch(a):
        raise CloudAgentWriteForbidden(
            f"agent test pattern rejected on production cloud lane {key} (use lane smoke)"
        )


def assert_cloud_purge_allowed(lane: str) -> None:
    key = CloudStore.normalize_lane(lane)
    if key in PRODUCTION_CLOUD_LANES:
        raise CloudAgentWriteForbidden(
            f"purge forbidden on production cloud lane {key} — user clears via b11 UI or local sqlite"
        )

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  lane    TEXT NOT NULL,
  layer   TEXT NOT NULL CHECK(layer IN ('active','archive')),
  role    TEXT NOT NULL CHECK(role IN ('user','assistant')),
  content TEXT NOT NULL,
  ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cloud_lane_layer ON messages(lane, layer, id);
"""


class CloudStore:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def normalize_lane(lane: str) -> str:
        key = str(lane or "").strip()
        if key not in _LANE_ALIASES:
            raise ValueError(f"unknown cloud lane: {lane}")
        return _LANE_ALIASES[key]

    def _rows(self, lane: str, *, layer: str, limit: int | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, role, content, ts FROM messages "
            "WHERE lane=? AND layer=? ORDER BY id ASC"
        )
        params: list[Any] = [lane, layer]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._lock, self._connect() as conn:
            cur = conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def _count_turns(self, msgs: list[dict[str, Any]]) -> int:
        n = 0
        i = 0
        while i < len(msgs):
            if msgs[i].get("role") != "user":
                i += 1
                continue
            if i + 1 < len(msgs) and msgs[i + 1].get("role") == "assistant":
                n += 1
                i += 2
            else:
                i += 1
        return n

    def stats(self, lane: str) -> dict[str, int]:
        lane = self.normalize_lane(lane)
        with self._lock, self._connect() as conn:
            active = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE lane=? AND layer='active'", (lane,)
            ).fetchone()[0]
            archive = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE lane=? AND layer='archive'", (lane,)
            ).fetchone()[0]
        active_msgs = self._rows(lane, layer="active")
        return {
            "active_msgs": int(active),
            "archive_msgs": int(archive),
            "active_turns": self._count_turns(active_msgs),
            "archive_turns": self._count_turns(self._rows(lane, layer="archive")),
        }

    def get_active(self, lane: str) -> list[dict[str, Any]]:
        lane = self.normalize_lane(lane)
        return self._rows(lane, layer="active")

    def get_archive(self, lane: str) -> list[dict[str, Any]]:
        lane = self.normalize_lane(lane)
        return self._rows(lane, layer="archive")

    def append_turn(
        self,
        lane: str,
        *,
        user: str,
        assistant: str,
        model: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        lane = self.normalize_lane(lane)
        user_text = str(user or "").strip()
        asst_text = str(assistant or "").strip()
        if not user_text or not asst_text:
            raise ValueError("user and assistant content required")
        assert_cloud_agent_write_allowed(lane, user_text, asst_text)
        now = time.time()
        archived_turns = 0
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO messages(lane, layer, role, content, ts) VALUES (?,?,?,?,?)",
                (lane, "active", "user", user_text, now),
            )
            meta = {"model": model} if model else {}
            if usage:
                meta["usage"] = usage
            asst_payload = asst_text
            if meta:
                asst_payload = json.dumps(
                    {"text": asst_text, **meta}, ensure_ascii=False
                )
            conn.execute(
                "INSERT INTO messages(lane, layer, role, content, ts) VALUES (?,?,?,?,?)",
                (lane, "active", "assistant", asst_payload, now + 0.001),
            )
            conn.commit()

            active = self._rows_locked(conn, lane, layer="active")
            archived_turns = self._roll_active_overflow_locked(conn, lane, active)

        active_out = self.get_active(lane)
        archive_out = self.get_archive(lane)
        st = self.stats(lane)
        return {
            "lane": lane,
            "active": self._map_client_messages(active_out),
            "archive": self._map_client_messages(archive_out),
            "archived_turns": archived_turns,
            **st,
        }

    def _roll_active_overflow_locked(
        self, conn: sqlite3.Connection, lane: str, active: list[dict[str, Any]]
    ) -> int:
        pairs = self._pair_indices(active)
        if len(pairs) <= ACTIVE_TURN_LIMIT:
            return 0
        overflow = pairs[: len(pairs) - ACTIVE_TURN_LIMIT]
        ids: list[int] = []
        for start, end in overflow:
            ids.extend(int(active[i]["id"]) for i in range(start, end + 1))
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE messages SET layer='archive' WHERE id IN ({placeholders})",
                ids,
            )
            conn.commit()
        return len(overflow)

    def clear_active(self, lane: str) -> dict[str, int]:
        # 雷3:本库是 cloud_memory.db(lane 列),≠ 8501 grid_store.messages;
        # 无 grid_mem 禁硬删触发器。生产 Cloud 记忆已迁 8501 store;此处仅 smoke 旁路。
        lane = self.normalize_lane(lane)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM messages WHERE lane=? AND layer='active'", (lane,)
            )
            conn.commit()
            return {"deleted": int(cur.rowcount or 0)}

    def purge_lane(self, lane: str) -> dict[str, int]:
        """Delete active + archive for one lane (smoke lane only for API)."""
        # 同上:sidecar cloud_memory.db,非 grid_store 生产表
        lane = self.normalize_lane(lane)
        assert_cloud_purge_allowed(lane)
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM messages WHERE lane=?", (lane,))
            conn.commit()
            return {"deleted": int(cur.rowcount or 0)}

    def _rows_locked(self, conn: sqlite3.Connection, lane: str, *, layer: str) -> list[dict[str, Any]]:
        cur = conn.execute(
            "SELECT id, role, content, ts FROM messages WHERE lane=? AND layer=? ORDER BY id ASC",
            (lane, layer),
        )
        return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def _pair_indices(msgs: list[dict[str, Any]]) -> list[tuple[int, int]]:
        pairs: list[tuple[int, int]] = []
        i = 0
        while i < len(msgs):
            if msgs[i].get("role") != "user":
                i += 1
                continue
            if i + 1 < len(msgs) and msgs[i + 1].get("role") == "assistant":
                pairs.append((i, i + 1))
                i += 2
            else:
                i += 1
        return pairs

    @staticmethod
    def _decode_assistant(content: str) -> dict[str, Any]:
        text = str(content or "")
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and "text" in obj:
                return {
                    "content": str(obj.get("text") or ""),
                    "model": obj.get("model"),
                    "usage": obj.get("usage"),
                }
        except json.JSONDecodeError:
            pass
        return {"content": text}

    def _map_client_messages(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            item: dict[str, Any] = {
                "id": row["id"],
                "role": row["role"],
                "ts": row["ts"],
            }
            if row["role"] == "assistant":
                decoded = self._decode_assistant(row["content"])
                item["content"] = decoded["content"]
                if decoded.get("model"):
                    item["model"] = decoded["model"]
                if decoded.get("usage"):
                    item["usage"] = decoded["usage"]
            else:
                item["content"] = row["content"]
            out.append(item)
        return out

    def snapshot(self, lane: str) -> dict[str, Any]:
        lane = self.normalize_lane(lane)
        with self._lock, self._connect() as conn:
            active = self._rows_locked(conn, lane, layer="active")
            self._roll_active_overflow_locked(conn, lane, active)
        active = self.get_active(lane)
        archive = self.get_archive(lane)
        st = self.stats(lane)
        return {
            "lane": lane,
            "active": self._map_client_messages(active),
            "archive": self._map_client_messages(archive),
            "active_turn_limit": ACTIVE_TURN_LIMIT,
            **st,
        }
