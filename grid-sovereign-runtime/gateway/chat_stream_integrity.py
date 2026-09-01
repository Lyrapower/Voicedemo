"""Cryptographic stream integrity — no lexical gates. Chunk chain for chat SSE."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any

GENESIS = "0" * 64


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def utf8_byte_len(text: str) -> int:
    return len((text or "").encode("utf-8"))


class StreamIntegrityTracker:
    """Rolling chunk chain for one chat stream."""

    def __init__(
        self,
        *,
        route_id: str,
        route: str,
        substrate_id: str,
        hmac_key: bytes | None = None,
    ) -> None:
        self.route_id = route_id
        self.route = route
        self.substrate_id = substrate_id
        self.hmac_key = hmac_key or os.getenv("GRID_STREAM_HMAC_KEY", "grid-stream-diag").encode()
        self.chunk_count = 0
        self.raw_accum = ""
        self.prev_chunk_hash = GENESIS
        self.started_at = time.time()
        self.chunks: list[dict[str, Any]] = []

    def append_chunk(self, piece: str) -> dict[str, Any]:
        self.chunk_count += 1
        self.raw_accum += piece
        chunk_hash = sha256_text(piece)
        rolling_hash = sha256_text(self.raw_accum)
        chain_msg = f"{self.route_id}:{self.chunk_count}:{self.prev_chunk_hash}:{chunk_hash}".encode()
        chain_hmac = hmac.new(self.hmac_key, chain_msg, hashlib.sha256).hexdigest()
        row = {
            "chunk_index": self.chunk_count,
            "piece_char_len": len(piece),
            "piece_utf8_bytes": utf8_byte_len(piece),
            "piece_hash": chunk_hash,
            "previous_chunk_hash": self.prev_chunk_hash,
            "rolling_hash": rolling_hash,
            "chain_hmac": chain_hmac,
        }
        self.prev_chunk_hash = chunk_hash
        self.chunks.append(row)
        return row

    def finalize(
        self,
        *,
        upstream_finish: str,
        terminal_event: str,
        sanitized_text: str | None = None,
    ) -> dict[str, Any]:
        sent = sanitized_text if sanitized_text is not None else self.raw_accum
        return {
            "route_id": self.route_id,
            "route": self.route,
            "substrate_id": self.substrate_id,
            "chunk_count": self.chunk_count,
            "char_len": len(self.raw_accum),
            "utf8_bytes": utf8_byte_len(self.raw_accum),
            "raw_accum_hash": sha256_text(self.raw_accum),
            "gateway_sent_text": sent,
            "gateway_sent_hash": sha256_text(sent),
            "upstream_finish_reason": upstream_finish,
            "terminal_event": terminal_event,
            "elapsed_ms": int((time.time() - self.started_at) * 1000),
            "chunks_tail": self.chunks[-5:],
        }
