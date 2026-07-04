from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = _REPO_ROOT / "data"
CONTEXT_BIN = DATA_DIR / "context.bin"
SESSIONS_DIR = DATA_DIR / "sessions"

MAGIC = b"GRIDCTX1"
MAX_BIN_BYTES = int(512_000)
MAX_TURNS = 80


@dataclass
class Turn:
    role: str
    content: str


class ContextBin:
    """Rolling token window — truncate old turns, never summarize meaning."""

    def __init__(self, path: Path = CONTEXT_BIN, max_bytes: int = MAX_BIN_BYTES):
        self.path = path
        self.max_bytes = max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_bytes(MAGIC)

    def _read_records(self) -> List[Turn]:
        raw = self.path.read_bytes()
        if len(raw) < len(MAGIC) or raw[: len(MAGIC)] != MAGIC:
            self.path.write_bytes(MAGIC)
            return []
        turns: List[Turn] = []
        offset = len(MAGIC)
        while offset + 5 <= len(raw):
            role_len = raw[offset]
            offset += 1
            if offset + role_len + 4 > len(raw):
                break
            role = raw[offset : offset + role_len].decode("utf-8", errors="replace")
            offset += role_len
            (content_len,) = struct.unpack_from(">I", raw, offset)
            offset += 4
            if offset + content_len > len(raw):
                break
            content = raw[offset : offset + content_len].decode("utf-8", errors="replace")
            offset += content_len
            if content:
                turns.append(Turn(role=role, content=content))
        return turns

    def _write_records(self, turns: List[Turn]) -> None:
        buf = bytearray(MAGIC)
        for t in turns:
            role_b = t.role.encode("utf-8")[:255]
            content_b = t.content.encode("utf-8")
            buf.append(len(role_b))
            buf.extend(role_b)
            buf.extend(struct.pack(">I", len(content_b)))
            buf.extend(content_b)
        while len(buf) > self.max_bytes and turns:
            turns.pop(0)
            buf = bytearray(MAGIC)
            for t in turns:
                role_b = t.role.encode("utf-8")[:255]
                content_b = t.content.encode("utf-8")
                buf.append(len(role_b))
                buf.extend(role_b)
                buf.extend(struct.pack(">I", len(content_b)))
                buf.extend(content_b)
        self.path.write_bytes(bytes(buf))

    def load(self) -> List[Turn]:
        return self._read_records()

    def replace(self, turns: List[Turn]) -> None:
        self._write_records(list(turns)[-MAX_TURNS:])

    def history_text(self) -> str:
        parts = []
        for t in self._read_records():
            parts.append(f"{t.role}: {t.content}")
        return "\n".join(parts)


class SessionStore:
    """Per-session JSON mirror (inspectable); context.bin holds rolling fidelity window."""

    def __init__(self, root: Path = SESSIONS_DIR, max_chars: int = 50_000, max_turns: int = MAX_TURNS):
        self.root = root
        self.max_chars = max_chars
        self.max_turns = max_turns
        self._locks: Dict[str, asyncio.Lock] = {}
        self.root.mkdir(parents=True, exist_ok=True)
        self.bin = ContextBin()

    def _path(self, session_id: str) -> Path:
        safe = "".join(ch for ch in session_id if ch.isalnum() or ch in ("-", "_", "."))
        if not safe:
            safe = "default"
        return self.root / f"{safe}.json"

    def _lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    async def load(self, session_id: str) -> List[Turn]:
        path = self._path(session_id)
        async with self._lock(session_id):
            if not path.exists():
                return self.bin.load()
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return self.bin.load()
        turns = []
        for item in data.get("turns", []):
            role = str(item.get("role", "user"))
            content = str(item.get("content", ""))
            if content:
                turns.append(Turn(role=role, content=content))
        return self.prune(turns) if turns else self.bin.load()

    async def save(self, session_id: str, turns: List[Turn]) -> None:
        path = self._path(session_id)
        payload: Dict[str, Any] = {
            "session_id": session_id,
            "turns": [{"role": t.role, "content": t.content} for t in turns],
        }
        async with self._lock(session_id):
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.bin.replace(turns)

    def prune(self, turns: List[Turn]) -> List[Turn]:
        pruned = list(turns)[-self.max_turns :]
        while pruned and sum(len(t.content) for t in pruned) > self.max_chars:
            pruned.pop(0)
        return pruned


sessions = SessionStore()
