"""Sentence splitter for voice TTS streaming — GRID_VOICE_SPEC §4.2."""
from __future__ import annotations

import re

_SPLIT_RE = re.compile(r"(?<=[。！？!?;；\n])|(?<=\.\s)(?=[A-Z\u4e00-\u9fff])")
_NUM_RE = re.compile(r"\d+\.\d+")


class SentenceSplitter:
    def __init__(self, *, min_len: int = 6, max_buf: int = 120) -> None:
        self.min_len = min_len
        self.max_buf = max_buf
        self._buf = ""

    def push(self, delta: str) -> list[str]:
        if not delta:
            return []
        self._buf += delta
        out: list[str] = []
        while True:
            if len(self._buf) >= self.max_buf:
                chunk, self._buf = self._buf[: self.max_buf], self._buf[self.max_buf :]
                out.append(chunk.strip())
                continue
            m = _SPLIT_RE.search(self._buf)
            if not m:
                break
            cut = m.end()
            chunk = self._buf[:cut].strip()
            self._buf = self._buf[cut:].lstrip()
            if not chunk:
                continue
            if len(chunk) < self.min_len and self._buf:
                self._buf = chunk + self._buf
                break
            if _NUM_RE.fullmatch(chunk.replace(" ", "")):
                self._buf = chunk + self._buf
                break
            out.append(chunk)
        return out

    def flush(self) -> str | None:
        tail = self._buf.strip()
        self._buf = ""
        return tail if tail else None
